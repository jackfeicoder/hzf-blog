"""Small production playback smoke check; never prints stream tokens/URLs/keys."""
import argparse
import json
import time
import httpx


def verify(play=False):
    base='http://127.0.0.1:8001'
    with httpx.Client(trust_env=False,timeout=35) as client:
        assert client.get(base+'/api/health').json()['status']=='ok'
        for path in ('/api/music/sources','/api/music/diagnostics'):
            assert client.get(base+path).status_code==401
        print('HEALTH_AND_ADMIN_PRIVACY_OK',flush=True)
        if not play:return
        for title,singer in (('还是分开','张叶蕾'),('Letting Go','蔡健雅')):
            found=client.get(base+'/api/music/search',params={'q':title+' '+singer,'source':'wy'})
            if found.status_code!=200:
                print(json.dumps({'song':title,'stage':'search','status':found.status_code},ensure_ascii=False),flush=True);continue
            songs=[row for row in found.json()['items'] if row['name'].strip().casefold()==title.casefold() and singer in row['singer']]
            if not songs:
                print(json.dumps({'song':title,'stage':'matching','status':'not_found'},ensure_ascii=False),flush=True);continue
            song=songs[0];attempted=[]
            started=time.monotonic()
            for batch in range(3):
                response=client.post(base+'/api/music/resolve',json={'song':song,'attempted':attempted})
                if response.status_code==200:break
                detail=response.json().get('detail',{})
                if not isinstance(detail,dict) or not detail.get('continue'):break
                attempted=detail.get('attempted',[])
            result={'song':title,'resolve':response.status_code,'seconds':round(time.monotonic()-started,2)}
            if response.status_code==200:
                data=response.json();result.update(source_id=data['source_id'],source_name=data['source_name'],platform=data['playback_song']['source'],attempts=len(data['attempted']))
                with client.stream('GET',base+data['url'],headers={'Range':'bytes=0-65535'}) as stream:
                    result['stream']=stream.status_code
                    total=0
                    for chunk in stream.iter_bytes():
                        total+=len(chunk)
                        if total>=65536:break
                    result['bytes']=total
                again=client.post(base+'/api/music/resolve',json={'song':song})
                result['repeat_resolve']=again.status_code
                if again.status_code==200:result['repeat_source_id']=again.json()['source_id']
                lyric=client.post(base+'/api/music/lyrics/resolve',json={'song':song,'playback_song':data['playback_song']})
                result['timed_lyrics']=lyric.status_code==200 and bool(lyric.json().get('lyric'))
            print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--play',action='store_true');args=parser.parse_args()
    verify(args.play)
