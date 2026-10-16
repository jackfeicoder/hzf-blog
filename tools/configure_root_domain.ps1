param(
    [Parameter(Mandatory=$true)][ValidateSet('Prepare','Certificate','Activate','Switch','Alias','Rollback','Status')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$BackupDir
)
$ErrorActionPreference = 'Stop'
$ssh = 'C:\Windows\System32\OpenSSH\ssh.exe'
$scp = 'C:\Windows\System32\OpenSSH\scp.exe'
$zone = [Environment]::GetEnvironmentVariable('CLOUDFLARE_ZONE_ID_120115_XYZ','User')
$token = [Environment]::GetEnvironmentVariable('CLOUDFLARE_API_TOKEN','User')
if (!$zone -or !$token) { throw 'Existing Cloudflare credential missing' }
$headers = @{Authorization='Bearer '+$token}
$base = 'https://api.cloudflare.com/client/v4/'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Cf([string]$Method,[string]$Path,$Body=$null) {
    $parameters = @{Method=$Method; Uri=$base+$Path; Headers=$headers; TimeoutSec=25}
    if ($null -ne $Body) { $parameters.ContentType='application/json'; $parameters.Body=$utf8.GetBytes(($Body | ConvertTo-Json -Depth 30 -Compress)) }
    try { $response = Invoke-RestMethod @parameters }
    catch {
        $status = [int]$_.Exception.Response.StatusCode
        if ($status -eq 404 -and $Method -eq 'GET') { return $null }
        throw "Cloudflare $Method $Path returned HTTP $status"
    }
    if (!$response.success) { throw ('Cloudflare API errors: '+ (($response.errors | ForEach-Object {$_.code}) -join ',')) }
    return $response.result
}
function Save($Name,$Value) {
    [IO.File]::WriteAllText((Join-Path $BackupDir $Name), ($Value | ConvertTo-Json -Depth 40), $utf8)
}
function Load($Name) { Get-Content -LiteralPath (Join-Path $BackupDir $Name) -Raw | ConvertFrom-Json }
function Remote($Arguments) {
    $output = & $ssh -o BatchMode=yes -o ConnectTimeout=10 aliyun $Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Remote domain deployment failed' }
    return ($output -join "`n")
}
$stage = '/tmp/hzf-root-domain-20261003'
$certDir = '/www/server/panel/vhost/cert/120115-blog'
$phaseBase = "zones/$zone/rulesets/phases/"

if ($Mode -eq 'Prepare') {
    if (Test-Path -LiteralPath $BackupDir) { throw 'Local backup directory already exists' }
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
    $dns = @(Cf GET "zones/$zone/dns_records?per_page=100")
    $root = @($dns | Where-Object {$_.name -eq '120115.xyz' -and $_.type -in @('A','AAAA','CNAME')})
    if ($root.Count -ne 1 -or $root[0].type -ne 'CNAME' -or $root[0].content -ne 'jackfeicoder.github.io') { throw 'Root DNS differs from inspected baseline' }
    $origin = Cf GET ($phaseBase+'http_request_origin/entrypoint')
    $config = Cf GET ($phaseBase+'http_config_settings/entrypoint')
    if (@($origin.rules | Where-Object {$_.expression -match '"120115\.xyz"'}).Count -or $config) { throw 'Root rule or configuration rules already exist; inspect first' }
    Save 'dns-before.json' $dns; Save 'origin-before.json' $origin; Save 'config-before.json' $config
    Save 'ssl-before.json' (Cf GET "zones/$zone/settings/ssl")
    Remote "mkdir -m 700 $stage" | Out-Null
    & $scp -o BatchMode=yes tools/deploy_root_domain.py "aliyun:$stage/deploy_root_domain.py"
    if ($LASTEXITCODE -ne 0) { throw 'Deployment helper upload failed' }
    $prepared = (Remote "python3 $stage/deploy_root_domain.py prepare") | ConvertFrom-Json
    Save 'server-before.json' $prepared
    Write-Output ('BACKUP='+$BackupDir+' SERVER_BACKUP='+$prepared.backup)
}
elseif ($Mode -eq 'Certificate') {
    $prepared = Load 'server-before.json'
    $certificate = Cf POST 'certificates' @{csr=$prepared.csr;hostnames=@('120115.xyz');request_type='origin-rsa';requested_validity=730}
    Save 'origin-certificate.json' $certificate
    [IO.File]::WriteAllText((Join-Path $BackupDir 'fullchain.pem'),$certificate.certificate,$utf8)
    Invoke-WebRequest -UseBasicParsing -Uri 'https://developers.cloudflare.com/ssl/static/origin_ca_rsa_root.pem' -OutFile (Join-Path $BackupDir 'origin-ca.pem') -TimeoutSec 25
    & $scp -o BatchMode=yes (Join-Path $BackupDir 'fullchain.pem') (Join-Path $BackupDir 'origin-ca.pem') "aliyun:$certDir/"
    if ($LASTEXITCODE -ne 0) { throw 'Public certificate upload failed' }
    Write-Output 'ORIGIN_CERTIFICATE_READY; private key stays on server'
}
elseif ($Mode -eq 'Activate') {
    $prepared = Load 'server-before.json'
    Remote "python3 $stage/deploy_root_domain.py activate $($prepared.backup)"
}
elseif ($Mode -eq 'Switch') {
    $before = @(Load 'dns-before.json')
    $root = @($before | Where-Object {$_.name -eq '120115.xyz' -and $_.type -eq 'CNAME'})[0]
    $current = Cf GET "zones/$zone/dns_records/$($root.id)"
    if ($current.type -ne $root.type -or $current.content -ne $root.content) { throw 'Root DNS changed concurrently' }
    $origin = Load 'origin-before.json'
    $state = @{origin_ruleset=$origin.id;origin_rule=$null;config_ruleset=$null;config_rule=$null;dns_changed=$false}
    Save 'changes.json' $state
    $added = Cf POST "zones/$zone/rulesets/$($origin.id)/rules" @{action='route';action_parameters=@{origin=@{port=8443}};description='root-blog-origin-8443';enabled=$true;expression='(http.host eq "120115.xyz")';ref='root_blog_origin_8443'}
    $state.origin_rule = @($added.rules | Where-Object {$_.ref -eq 'root_blog_origin_8443'})[0].id
    Save 'changes.json' $state
    $added = Cf PUT ($phaseBase+'http_config_settings/entrypoint') @{description='Per-host TLS configuration';rules=@(@{action='set_config';action_parameters=@{ssl='strict'};description='root-blog-strict-tls';enabled=$true;expression='(http.host eq "120115.xyz")';ref='root_blog_strict_tls'})}
    $state.config_ruleset=$added.id; $state.config_rule=@($added.rules | Where-Object {$_.ref -eq 'root_blog_strict_tls'})[0].id
    Save 'changes.json' $state
    $body=@{type='A';name='120115.xyz';content='47.94.93.71';ttl=$root.ttl;proxied=$true}
    if ($root.comment) {$body.comment=$root.comment}
    Cf PUT "zones/$zone/dns_records/$($root.id)" $body | Out-Null
    $state.dns_changed=$true; Save 'changes.json' $state
    Write-Output 'ROOT_DNS_SWITCHED; root-only strict TLS and origin port 8443'
}
elseif ($Mode -eq 'Alias') {
    $root=@((Load 'dns-before.json') | Where-Object {$_.name -eq '120115.xyz' -and $_.type -eq 'CNAME'})[0]
    $current=Cf GET "zones/$zone/dns_records/$($root.id)"
    if ($current.type -ne 'A' -or $current.content -ne '47.94.93.71') {throw 'Unexpected root record before alias test'}
    Cf PUT "zones/$zone/dns_records/$($root.id)" @{type='CNAME';name='120115.xyz';content='blog.120115.xyz';ttl=$root.ttl;proxied=$true} | Out-Null
    Write-Output 'ROOT_ALIAS_SWITCHED_TO_EXISTING_BLOG'
}
elseif ($Mode -eq 'Rollback') {
    if (Test-Path (Join-Path $BackupDir 'changes.json')) {
        $state=Load 'changes.json'
        if ($state.dns_changed) {
            $root=@((Load 'dns-before.json') | Where-Object {$_.name -eq '120115.xyz' -and $_.type -eq 'CNAME'})[0]
            $current=Cf GET "zones/$zone/dns_records/$($root.id)"
            if (!(($current.type -eq 'A' -and $current.content -eq '47.94.93.71') -or ($current.type -eq 'CNAME' -and $current.content -eq 'blog.120115.xyz'))) {throw 'DNS changed concurrently; review rollback'}
            Cf PUT "zones/$zone/dns_records/$($root.id)" @{type=$root.type;name=$root.name;content=$root.content;ttl=$root.ttl;proxied=$root.proxied} | Out-Null
        }
        if ($state.origin_rule) {Cf DELETE "zones/$zone/rulesets/$($state.origin_ruleset)/rules/$($state.origin_rule)" | Out-Null}
        if ($state.config_rule) {
            Cf DELETE "zones/$zone/rulesets/$($state.config_ruleset)/rules/$($state.config_rule)" | Out-Null
            $remaining=Cf GET "zones/$zone/rulesets/$($state.config_ruleset)"
            if (@($remaining.rules).Count -eq 0) {Cf DELETE "zones/$zone/rulesets/$($state.config_ruleset)" | Out-Null}
        }
    }
    $prepared=Load 'server-before.json'
    Remote "python3 $stage/deploy_root_domain.py rollback $($prepared.backup)"
    Save 'rollback-completed.json' @{completed=$true;date=(Get-Date).ToUniversalTime().ToString('o')}
    Write-Output 'ROOT_DNS_AND_RULES_ROLLED_BACK'
}
else {
    $dns=@(Cf GET "zones/$zone/dns_records?per_page=100")
    $before=@(Load 'dns-before.json')
    $otherBefore=@($before | Where-Object {$_.name -ne '120115.xyz' -or $_.type -notin @('A','AAAA','CNAME')})
    foreach($record in $otherBefore) {
        $current=@($dns | Where-Object {$_.id -eq $record.id})
        if ($current.Count -ne 1 -or $current[0].type -ne $record.type -or $current[0].content -ne $record.content -or $current[0].proxied -ne $record.proxied) {throw 'An unrelated DNS record changed'}
    }
    $ssl=Cf GET "zones/$zone/settings/ssl"
    if ($ssl.value -ne (Load 'ssl-before.json').value) {throw 'Global SSL setting changed'}
    Write-Output 'UNRELATED_DNS_AND_GLOBAL_SSL_UNCHANGED'
    $dns | Where-Object {$_.name -eq '120115.xyz' -and $_.type -in @('A','CNAME')} | Select-Object name,type,content,proxied | ConvertTo-Json
}
$headers=$null; $token=$null
