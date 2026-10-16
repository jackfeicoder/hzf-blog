param(
  [Parameter(Mandatory=$true)][ValidateSet('Prepare','Redirect','Status','RetireHexo','Rollback')][string]$Mode,
  [Parameter(Mandatory=$true)][string]$BackupDir
)
$ErrorActionPreference = 'Stop'
$zone = [Environment]::GetEnvironmentVariable('CLOUDFLARE_ZONE_ID_120115_XYZ','User')
$cfToken = [Environment]::GetEnvironmentVariable('CLOUDFLARE_API_TOKEN','User')
$githubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN','User')
if (!$githubToken) { $githubToken = $env:GITHUB_TOKEN }
if (!$zone -or !$cfToken) { throw 'Cloudflare configured credentials missing' }
$utf8 = [Text.UTF8Encoding]::new($false)
$repo = 'jackfeicoder/jackfeicoder.github.io'
$phase = "zones/$zone/rulesets/phases/http_request_dynamic_redirect/entrypoint"
$ref = 'legacy_hexo_to_blog_8443'
$destination = 'https://blog.120115.xyz:8443/'
$resolvedBackup = [IO.Path]::GetFullPath($BackupDir)
$backupRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.local-history')) + [IO.Path]::DirectorySeparatorChar
if (!$resolvedBackup.StartsWith($backupRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup directory must be inside project .local-history' }
$BackupDir = $resolvedBackup

function Call-Api($Service,$Method,$Path,$Body=$null) {
  if ($Service -eq 'cf') {
    $uri = 'https://api.cloudflare.com/client/v4/'+$Path
    $headers = @{Authorization='Bearer '+$cfToken}
  } else {
    $uri = 'https://api.github.com/'+$Path
    $headers = @{Accept='application/vnd.github+json';'X-GitHub-Api-Version'='2022-11-28';'User-Agent'='hzf-blog-domain-maintenance'}
    if ($githubToken) { $headers.Authorization='Bearer '+$githubToken }
  }
  $params = @{Uri=$uri;Method=$Method;Headers=$headers;TimeoutSec=25}
  if ($null -ne $Body) { $params.ContentType='application/json'; $params.Body=$utf8.GetBytes(($Body | ConvertTo-Json -Depth 50 -Compress)) }
  try { $response = Invoke-RestMethod @params }
  catch {
    $status = [int]$_.Exception.Response.StatusCode
    if ($status -eq 404 -and $Method -eq 'GET') { return $null }
    throw "$Service $Method $Path returned HTTP $status"
  }
  if ($Service -eq 'cf') {
    if (!$response.success) { throw ('Cloudflare error codes: '+(($response.errors | ForEach-Object {$_.code}) -join ',')) }
    return $response.result
  }
  return $response
}
function Save($Name,$Value) { [IO.File]::WriteAllText((Join-Path $BackupDir $Name),($Value | ConvertTo-Json -Depth 60),$utf8) }
function Load($Name) { Get-Content -LiteralPath (Join-Path $BackupDir $Name) -Raw | ConvertFrom-Json }

if ($Mode -eq 'Prepare') {
  if (Test-Path -LiteralPath $BackupDir) { throw 'Backup directory already exists' }
  New-Item -ItemType Directory -Path $BackupDir | Out-Null
  $dns = @(Call-Api cf GET "zones/$zone/dns_records?per_page=100")
  $root = @($dns | Where-Object {$_.name -eq '120115.xyz' -and $_.type -in @('A','AAAA','CNAME')})
  if ($root.Count -ne 1 -or $root[0].type -ne 'CNAME' -or $root[0].content -ne 'jackfeicoder.github.io' -or !$root[0].proxied) { throw 'Root DNS differs from expected proxied Hexo baseline; review first' }
  $redirects = Call-Api cf GET $phase
  Save 'dns-before.json' $dns
  Save 'redirects-before.json' $redirects
  Save 'origin-before.json' (Call-Api cf GET "zones/$zone/rulesets/phases/http_request_origin/entrypoint")
  Save 'ssl-before.json' (Call-Api cf GET "zones/$zone/settings/ssl")
  $site = Call-Api github GET "repos/$repo/pages"
  Save 'github-pages-before.json' $site
  if ($site) {
    Save 'repository-before.json' (Call-Api github GET "repos/$repo")
    Save 'workflows-before.json' (Call-Api github GET "repos/$repo/actions/workflows")
  }
  $targets = @('120115.xyz')
  $www = @($dns | Where-Object {$_.name -eq 'www.120115.xyz' -and $_.type -eq 'CNAME' -and $_.content -eq 'jackfeicoder.github.io' -and $_.proxied})
  if ($www.Count -eq 1) { $targets += 'www.120115.xyz' }
  Save 'plan.json' @{hosts=$targets;destination=$destination;status=302;repository=$repo}
  Write-Output ('BACKUP='+$BackupDir)
  $dns | Where-Object {$_.name -in @('120115.xyz','www.120115.xyz','blog.120115.xyz','feitools.120115.xyz','img.120115.xyz')} | Select-Object name,type,content,proxied | ConvertTo-Json
  Write-Output ('EXISTING_REDIRECT_RULES='+@($redirects.rules | Where-Object {$_}).Count)
  if ($redirects) { $redirects.rules | Select-Object id,description,expression,action,enabled | ConvertTo-Json }
  if ($site) { $site | Select-Object html_url,cname,status,build_type,source | ConvertTo-Json } else { Write-Output 'GITHUB_PAGES_NOT_FOUND; no site will be disabled until identified' }
}
elseif ($Mode -eq 'Redirect') {
  $plan = Load 'plan.json'
  $before = Load 'redirects-before.json'
  $current = Call-Api cf GET $phase
  if (($current | ConvertTo-Json -Depth 60 -Compress) -ne ($before | ConvertTo-Json -Depth 60 -Compress)) { throw 'Redirect rules changed since backup; inspect first' }
  if (@($current.rules | Where-Object {$_.ref -eq $ref}).Count) { throw 'Managed redirect already exists' }
  $expression = '(http.host in {' + (($plan.hosts | ForEach-Object {'"'+$_+'"'}) -join ' ') + '})'
  $rule = @{ref=$ref;description='Retired Hexo domain to current blog (temporary 302)';expression=$expression;enabled=$true;action='redirect';action_parameters=@{from_value=@{target_url=@{value=$destination};status_code=302;preserve_query_string=$false}}}
  if ($current) {
    # Insert just this rule, preserve every existing rule verbatim.
    $rule.position=@{index=1}
    $result = Call-Api cf POST "zones/$zone/rulesets/$($current.id)/rules" $rule
  } else {
    $result = Call-Api cf POST "zones/$zone/rulesets" @{name='Domain redirects';kind='zone';phase='http_request_dynamic_redirect';rules=@($rule)}
  }
  $added = @($result.rules | Where-Object {$_.ref -eq $ref})
  if ($added.Count -ne 1) { throw 'Redirect API response did not include expected rule' }
  Save 'changes.json' @{ruleset=$result.id;rule=$added[0].id;created_ruleset=($null -eq $current);dns_changed=@();pages_retired=$false}
  Write-Output 'REDIRECT_CREATED_302; DNS and server unchanged'
}
elseif ($Mode -eq 'Status') {
  $current = Call-Api cf GET $phase
  $managed = @($current.rules | Where-Object {$_.ref -eq $ref})
  $managed | Select-Object description,expression,enabled,action_parameters | ConvertTo-Json -Depth 10
  $beforeDns = @(Load 'dns-before.json')
  $nowDns = @(Call-Api cf GET "zones/$zone/dns_records?per_page=100")
  $state = Load 'changes.json'
  foreach ($record in $beforeDns | Where-Object {$_.id -notin $state.dns_changed}) {
    $now = @($nowDns | Where-Object {$_.id -eq $record.id})
    if ($now.Count -ne 1 -or $now[0].type -ne $record.type -or $now[0].content -ne $record.content -or $now[0].proxied -ne $record.proxied) { throw 'Unrelated DNS changed' }
  }
  $origin = Call-Api cf GET "zones/$zone/rulesets/phases/http_request_origin/entrypoint"
  if (($origin | ConvertTo-Json -Depth 60 -Compress) -ne ((Load 'origin-before.json') | ConvertTo-Json -Depth 60 -Compress)) { throw 'Origin rules changed' }
  if ((Call-Api cf GET "zones/$zone/settings/ssl").value -ne (Load 'ssl-before.json').value) { throw 'Global TLS changed' }
  Write-Output 'UNRELATED_DNS_ORIGIN_TLS_UNCHANGED'
}
elseif ($Mode -eq 'RetireHexo') {
  # Executed only after the public redirect has been separately tested.
  $site = Load 'github-pages-before.json'
  $state = Load 'changes.json'
  if (!$site -or $site.cname -ne '120115.xyz') { throw 'Expected Hexo GitHub Pages site not identified' }
  if (!(Test-Path -LiteralPath (Join-Path $BackupDir 'hexo-repository.zip'))) { throw 'Repository archive backup required before disabling Pages' }
  $current = Call-Api github GET "repos/$repo/pages"
  if ($current.cname -ne $site.cname -or $current.build_type -ne $site.build_type) { throw 'GitHub Pages configuration changed' }
  $rules = Call-Api cf GET $phase
  $managed = @($rules.rules | Where-Object {$_.id -eq $state.rule -and $_.ref -eq $ref -and $_.enabled -and $_.action_parameters.from_value.target_url.value -eq $destination})
  if ($managed.Count -ne 1) { throw 'Expected active redirect missing' }
  $plan = Load 'plan.json'
  $dns = @(Load 'dns-before.json')
  foreach ($record in $dns | Where-Object {$_.name -in $plan.hosts -and $_.type -eq 'CNAME'}) {
    $now = Call-Api cf GET "zones/$zone/dns_records/$($record.id)"
    if ($now.type -ne $record.type -or $now.content -ne $record.content -or $now.proxied -ne $record.proxied) { throw 'Legacy DNS changed concurrently' }
    # Official Cloudflare redirect-only setup: documentation address, not an
    # origin. This also removes a dangling GitHub Pages CNAME after retirement.
    $body = @{type='A';name=$record.name;content='192.0.2.1';ttl=$record.ttl;proxied=$true}
    if ($record.comment) { $body.comment=$record.comment }
    if ($record.tags) { $body.tags=@($record.tags) }
    Call-Api cf PUT "zones/$zone/dns_records/$($record.id)" $body | Out-Null
    $state.dns_changed=@($state.dns_changed)+$record.id
    Save 'changes.json' $state
  }
  Call-Api github DELETE "repos/$repo/pages" | Out-Null
  $state.pages_retired=$true
  Save 'changes.json' $state
  Write-Output 'HEXO_PAGES_DISABLED; repository and commits retained'
}
else {
  $state = Load 'changes.json'
  if ($state.pages_retired -and $state.pages_retirement_method -eq 'ui-source-none') {
    # The current API token lacks Pages write permission. Restore Pages through
    # the logged-in UI first, before changing DNS or removing the redirect.
    $site = Load 'github-pages-before.json'
    $current = Call-Api github GET "repos/$repo/pages"
    if (!$current -or $current.source.branch -ne $site.source.branch -or $current.source.path -ne $site.source.path -or $current.cname -ne $site.cname) {
      throw 'Restore original Pages settings in GitHub UI (main, /, custom domain 120115.xyz) before DNS rollback'
    }
  }
  $dns = @(Load 'dns-before.json')
  foreach ($record in $dns | Where-Object {$_.id -in $state.dns_changed}) {
    $now = Call-Api cf GET "zones/$zone/dns_records/$($record.id)"
    if ($now.type -ne 'A' -or $now.content -ne '192.0.2.1') { throw 'Legacy DNS changed concurrently; review rollback' }
    $body = @{type=$record.type;name=$record.name;content=$record.content;ttl=$record.ttl;proxied=$record.proxied}
    if ($record.comment) { $body.comment=$record.comment }
    if ($record.tags) { $body.tags=@($record.tags) }
    Call-Api cf PUT "zones/$zone/dns_records/$($record.id)" $body | Out-Null
  }
  if ($state.pages_retired -and $state.pages_retirement_method -ne 'ui-source-none') {
    $site = Load 'github-pages-before.json'
    $current = Call-Api github GET "repos/$repo/pages"
    if ($current) { throw 'A Pages site already exists; inspect before restoring' }
    Call-Api github POST "repos/$repo/pages" @{build_type=$site.build_type;source=@{branch=$site.source.branch;path=$site.source.path}} | Out-Null
    Call-Api github PUT "repos/$repo/pages" @{cname=$site.cname;https_enforced=$site.https_enforced} | Out-Null
  }
  $current = Call-Api cf GET $phase
  $managed = @($current.rules | Where-Object {$_.id -eq $state.rule -and $_.ref -eq $ref})
  if ($managed.Count -ne 1) { throw 'Expected managed redirect missing; inspect first' }
  Call-Api cf DELETE "zones/$zone/rulesets/$($state.ruleset)/rules/$($state.rule)" | Out-Null
  Write-Output 'REDIRECT_REMOVED; original DNS retained'
}
$cfToken=$null; $githubToken=$null
