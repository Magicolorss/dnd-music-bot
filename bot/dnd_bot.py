#!/usr/bin/env python3
"""DnD Music Bot — Pro with Bandcamp + SoundCloud + YouTube + icons"""
import os, sys, time, json, logging, requests, urllib.parse, threading, subprocess
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dnd-bot")

TOKEN=os.environ.get("TELEGRAM_TOKEN",""); LIDARR_URL=os.environ.get("LIDARR_URL","http://localhost:8686")
LIDARR_KEY=os.environ.get("LIDARR_API_KEY",""); OR_KEY=os.environ.get("OPENROUTER_API_KEY","")
ALLOWED=os.environ.get("ALLOWED_USERS","").split(","); TG_API="https://api.telegram.org/bot"+TOKEN
YT_DIR="/downloads"

notified={}; pending={}

# ICONS - emoji-based platform icons for Telegram buttons
ICON = {"soulseek":"🔵","bandcamp":"🟣","youtube":"🔴","soundcloud":"🟠","torrent":"⚡","musicbrainz":"🎵"}

def tg_send(cid,text,buttons=None):
    data={"chat_id":cid,"text":text,"parse_mode":"Markdown"}
    if buttons: data["reply_markup"]=json.dumps({"inline_keyboard":buttons})
    try: r=requests.post(TG_API+"/sendMessage",json=data,timeout=15); return r.json().get("result",{}).get("message_id")
    except: return None

def tg_photo(cid,url,caption,buttons=None):
    data={"chat_id":cid,"photo":url,"caption":caption,"parse_mode":"Markdown"}
    if buttons: data["reply_markup"]=json.dumps({"inline_keyboard":buttons})
    try: r=requests.post(TG_API+"/sendPhoto",json=data,timeout=20); return r.json().get("result",{}).get("message_id")
    except: return None

def tg_cb(qid,text):
    try: requests.post(TG_API+"/answerCallbackQuery",json={"callback_query_id":qid,"text":text},timeout=10)
    except: pass

def lidarr(method,path,data=None):
    headers={"X-Api-Key":LIDARR_KEY,"Content-Type":"application/json"}
    url=LIDARR_URL+"/api/v1/"+path.lstrip("/")
    try: r=getattr(requests,method.lower())(url,headers=headers,json=data,timeout=10); return r.json() if r.status_code in(200,201,202) else None
    except: return None

def allowed(cid):
    if not ALLOWED or ALLOWED==[""]: return True
    return str(cid) in ALLOWED

# ── Lidarr library helpers ────────────────────────────────────────
def lidarr_artists():
    r=lidarr("GET","artist?includeAllArtistAlbums=true")
    if not r: return []
    r.sort(key=lambda a: a.get("artistName","").lower())
    return r

def lidarr_albums(aid):
    return lidarr("GET",f"album?artistId={aid}") or []

def lidarr_tracks(aid):
    return lidarr("GET",f"track?albumId={aid}") or []

def lidarr_missing(page=1,size=20):
    return lidarr("GET",f"wanted/missing?page={page}&pageSize={size}&sortKey=albums.title&sortDirection=ascending") or {}

def lidarr_stats():
    arts=lidarr_artists()
    if not arts: return None
    total_albums=sum(a.get("statistics",{}).get("albumCount",0) for a in arts)
    total_tracks=sum(a.get("statistics",{}).get("trackCount",0) for a in arts)
    total_files=sum(a.get("statistics",{}).get("trackFileCount",0) for a in arts)
    total_size=sum(a.get("statistics",{}).get("sizeOnDisk",0) for a in arts)
    # Count monitored vs unmonitored
    monitored=sum(1 for a in arts if a.get("monitored"))
    return {"artists":len(arts),"albums":total_albums,"tracks":total_tracks,"files":total_files,"size":total_size,"monitored":monitored}

def get_quality(album):
    """Best quality string from album's tracks."""
    qs=lidarr_tracks(album.get("id"))
    if not qs: return "?"
    quals=set()
    for t in qs:
        f=t.get("trackFile")
        if f:
            q=f.get("quality",{}).get("quality",{}).get("name","?")
            quals.add(q)
    if not quals: return "❌ Missing"
    return ", ".join(sorted(quals))

# AI
def ai_guess(text):
    if not OR_KEY: return None
    try:
        r=requests.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":"Bearer "+OR_KEY,"Content-Type":"application/json"},
            json={"model":"google/gemini-2.0-flash-lite-preview-02-05:free",
                "messages":[{"role":"system","content":"You are a music expert. Return JSON: {\"corrected\":\"Artist Name\",\"albums\":[\"A1\",\"A2\",\"A3\"],\"bio\":\"One sentence\"} or {\"error\":\"unknown\"}. No markdown."},
                            {"role":"user","content":"Search: "+text}],
                "temperature":0.1,"max_tokens":300},timeout=15)
        c=r.json()["choices"][0]["message"]["content"].strip()
        if c.startswith("```"): c=c.split("\n",1)[1].rsplit("```",1)[0]
        return json.loads(c)
    except Exception as e: log.error("ai: "+str(e)); return None

# MusicBrainz
def mb_search(name):
    try: r=requests.get("https://musicbrainz.org/ws/2/artist/",params={"query":name,"fmt":"json","limit":6},headers={"User-Agent":"DnDBot/1.0"},timeout=15); return r.json().get("artists",[])
    except: return []
def mb_albums(mbid, atype="album"):
    try:
        r=requests.get("https://musicbrainz.org/ws/2/release-group/",params={"artist":mbid,"fmt":"json","limit":100,"type":atype},headers={"User-Agent":"DnDBot/1.0"},timeout=15)
        out=[]
        for g in r.json().get("release-groups",[]):
            y=g.get("first-release-date","")[:4] if g.get("first-release-date") else "9999"
            out.append({"title":g.get("title","?"),"year":y,"id":g.get("id","")})
        # Sort by year ascending (oldest first)
        out.sort(key=lambda x: (x["year"] if x["year"].isdigit() else 9999, x["title"]))
        return out
    except: return []
def get_cover(mbid):
    try: r=requests.get("https://coverartarchive.org/release-group/"+mbid,timeout=8); imgs=r.json().get("images",[]); return imgs[0].get("thumbnails",{}).get("large") or imgs[0].get("image") if imgs else None
    except: return None
def artist_cover(aname):
    a=mb_search(aname)
    if not a: return None
    for al in mb_albums(a[0]["id"]):
        c=get_cover(al["id"])
        if c: return c
    return None

# ── YouTube ─────────────────────────────────────────────────────
def yt_search(query,limit=5):
    try: r=subprocess.run(["yt-dlp","--flat-playlist","--print","%(id)s|%(title)s|%(duration)s","ytsearch"+str(limit)+":"+query],capture_output=True,text=True,timeout=30); return [{"id":p[0],"title":p[1],"duration":p[2].strip() if len(p)>2 else ""} for l in r.stdout.strip().split("\n") if l and len(p:=l.split("|",2))>=2]
    except Exception as e: log.error("yt: "+str(e)); return []

def yt_download(vid,title,cid):
    safe="".join(c for c in title[:40] if c.isalnum() or c in " -_"); outdir=YT_DIR+"/YouTube/"+safe; os.makedirs(outdir,exist_ok=True)
    tg_send(cid,ICON["youtube"]+" Downloading *"+title[:50]+"* from YouTube...\nBest native audio (Opus 160kbps) + cover art.")
    r=subprocess.run(["yt-dlp","-f","bestaudio[ext=m4a]/bestaudio","--embed-metadata","--embed-thumbnail","--add-metadata",
        "--parse-metadata","%(title)s:%(artist)s","--parse-metadata","%(title)s:%(album)s","-o",outdir+"/%(title)s.%(ext)s",
        "https://www.youtube.com/watch?v="+vid],capture_output=True,text=True,timeout=600)
    if r.returncode==0: tg_send(cid,"✅ *"+title[:50]+"* from YouTube with cover art!\n⚠️ Lossy ~160kbps Opus."); lidarr("POST","command",{"name":"DownloadedAlbumsScan"})
    else: tg_send(cid,"❌ YouTube failed.\n"+r.stderr[-200:])

# ── Bandcamp (real FLAC!) ───────────────────────────────────────
def bc_search(query,limit=5):
    try: r=subprocess.run(["yt-dlp","--flat-playlist","--print","%(url)s|%(title)s|%(uploader)s","bandcamp:search:"+query],capture_output=True,text=True,timeout=30); return [{"url":p[0],"title":p[1],"artist":p[2] if len(p)>2 else ""} for l in r.stdout.strip().split("\n") if l and len(p:=l.split("|",2))>=2][:limit]
    except Exception as e: log.error("bc: "+str(e)); return []

def bc_download(url,title,cid):
    safe="".join(c for c in title[:40] if c.isalnum() or c in " -_"); outdir=YT_DIR+"/Bandcamp/"+safe; os.makedirs(outdir,exist_ok=True)
    tg_send(cid,ICON["bandcamp"]+" Downloading *"+title[:50]+"* from Bandcamp...\n**Real FLAC quality!**")
    r=subprocess.run(["yt-dlp","-f","bestaudio","--embed-metadata","--embed-thumbnail","--add-metadata",
        "-o",outdir+"/%(title)s.%(ext)s",url],capture_output=True,text=True,timeout=600)
    if r.returncode==0: tg_send(cid,"✅ *"+title[:50]+"* from Bandcamp — **real FLAC!**\n📂 Lidarr will pick it up."); lidarr("POST","command",{"name":"DownloadedAlbumsScan"})
    else: tg_send(cid,"❌ Bandcamp failed.\n"+r.stderr[-200:])

# ── SoundCloud ──────────────────────────────────────────────────
def sc_search(query,limit=5):
    try: r=subprocess.run(["yt-dlp","--flat-playlist","--print","%(id)s|%(title)s|%(uploader)s|%(duration)s","scsearch"+str(limit)+":"+query],capture_output=True,text=True,timeout=30); return [{"id":p[0],"title":p[1],"artist":p[2] if len(p)>2 else "","duration":p[3] if len(p)>3 else ""} for l in r.stdout.strip().split("\n") if l and len(p:=l.split("|",2))>=2]
    except Exception as e: log.error("sc: "+str(e)); return []

def sc_download(vid,title,cid):
    safe="".join(c for c in title[:40] if c.isalnum() or c in " -_"); outdir=YT_DIR+"/SoundCloud/"+safe; os.makedirs(outdir,exist_ok=True)
    tg_send(cid,ICON["soundcloud"]+" Downloading *"+title[:50]+"* from SoundCloud...")
    r=subprocess.run(["yt-dlp","-f","bestaudio","--embed-metadata","--embed-thumbnail","--add-metadata",
        "-o",outdir+"/%(title)s.%(ext)s","https://soundcloud.com/"+vid],capture_output=True,text=True,timeout=600)
    if r.returncode==0: tg_send(cid,"✅ *"+title[:50]+"* from SoundCloud with cover art!\n⚠️ Lossy quality."); lidarr("POST","command",{"name":"DownloadedAlbumsScan"})
    else: tg_send(cid,"❌ SoundCloud failed.\n"+r.stderr[-200:])

# ── Lidarr ops ──────────────────────────────────────────────────
def do_add(cid,mbid,name,album_ids=None):
    """Add artist to Lidarr. If album_ids list provided, only monitor those albums."""
    lookup=lidarr("GET","artist/lookup?term="+urllib.parse.quote("lidarr:"+mbid))
    if lookup and len(lookup)>0 and lookup[0].get("id",0)>0:
        ex=lookup[0]
        if ex.get("monitored"):
            tg_send(cid,"✅ *"+name+"* already in Lidarr!")
            return
        ex["monitored"]=True; ex["addOptions"]={"searchForMissingAlbums":True}
        lidarr("PUT","artist/"+str(ex["id"]),ex); tg_send(cid,"✅ *"+name+"* now monitored! Searching..."); return
    body={"foreignArtistId":mbid,"artistName":name,"monitored":True,"monitorNewItems":"all",
        "rootFolderPath":"/music","qualityProfileId":2,"metadataProfileId":1,
        "addOptions":{"searchForMissingAlbums":True,"searchForNewAlbums":True}}
    if album_ids:
        body["albumsToMonitor"]=album_ids
        body["addOptions"]["searchForMissingAlbums"]=True
    add=lidarr("POST","artist",body)
    if add: tg_send(cid,"✅ *"+name+"* added! "+(str(len(album_ids))+" album(s) will be downloaded." if album_ids else "Auto-downloading..."))
    else: tg_send(cid,"❌ Failed to add *"+name+"*")

# ── UI ──────────────────────────────────────────────────────────
def picker(cid,artists):
    """Multiple matches found — show compact buttons + all platforms."""
    msg="Multiple matches:\n"
    for i,a in enumerate(artists):
        n=a.get("name","?")[:35]
        d=a.get("disambiguation","")
        s=a.get("score",0)
        msg+=str(i+1)+". "+n+(" ("+d[:15]+")" if d else "")+" - "+str(s)+"%\n"
    msg+="\nWhich one?"
    btns=[[{"text":str(i+1)+". "+artists[i].get("name","?")[:15],"callback_data":"pick:"+str(i)}] for i in range(len(artists))]
    btns.append([{"text":ICON["bandcamp"]+" Bandcamp","callback_data":"bc:"+artists[0].get("name","")[:40]}])
    btns.append([{"text":ICON["youtube"]+" YouTube","callback_data":"yt:"+artists[0].get("name","")[:40]}])
    pending[cid]={"artists":artists}; tg_send(cid,msg,btns)

def show_confirm(cid,artist):
    aname=artist.get("name","?"); d=artist.get("disambiguation",""); cover=artist_cover(aname)
    cap=ICON["musicbrainz"]+" *"+aname+"*"+(" ("+d+")" if d else "")
    cap+="\n\nWhat content type to browse?"
    btns=[[{"text":"💿 Albums","callback_data":"content:album:"+aname[:30]},
           {"text":"🎵 Singles","callback_data":"content:single:"+aname[:30]}],
          [{"text":"📀 EPs","callback_data":"content:ep:"+aname[:30]},
           {"text":"📚 Compilations","callback_data":"content:compilation:"+aname[:30]}]]
    pending[cid]={"artists":[artist]}
    if cover: tg_photo(cid,cover,cap,btns)
    else: tg_send(cid,cap,btns)

def show_album_list(cid,artist,atype,aname):
    mbid=artist["id"]; albums=mb_albums(mbid,atype); cover=artist_cover(aname)
    type_icons={"album":"💿","single":"🎵","ep":"📀","compilation":"📚"}
    icon=type_icons.get(atype,"📀")
    cap=icon+" *"+aname+"* — *"+atype.capitalize()+"s*\n"
    if not albums: cap+="\nNo "+atype+"s found for this artist."
    else:
        cap+="\nChoose:"
        pending[cid]={"artists":[artist],"albums":albums}
    btns=[]
    for a in albums[:25]:
        label=a["title"][:25]+(" ("+a["year"]+")" if a["year"] else "")
        btns.append([{"text":"🎵 "+label,"callback_data":"album:"+a["id"]+":"+a["title"][:20]}])
    btns.append([{"text":"📥 Add all + download","callback_data":"add:"+mbid+":"+aname}])
    btns.append([{"text":"🔙 Back","callback_data":"back:"+aname[:30]}])
    if cover: tg_photo(cid,cover,cap,btns)
    else: tg_send(cid,cap,btns)

def show_platform_picker(cid,query):
    """Show all platform options when artist not found on MusicBrainz."""
    btns=[[{"text":ICON["bandcamp"]+" Bandcamp (FLAC!)","callback_data":"bc:"+query[:40]},
           {"text":ICON["youtube"]+" YouTube","callback_data":"yt:"+query[:40]}],
          [{"text":ICON["soundcloud"]+" SoundCloud","callback_data":"sc:"+query[:40]},
           {"text":"❌ Cancel","callback_data":"cancel"}]]
    tg_send(cid,"Couldn't find *"+query.replace("*","")+"* on MusicBrainz.\n\nChoose a source:",btns)

def show_results(cid,title,results,source,prefix,download_fn):
    if not results: tg_send(cid,"❌ Nothing found on "+source+" for *"+title+"*"); return
    cap=ICON.get(source.lower(),"🔍")+" *"+source+" results for:* "+title+"\n\n"
    for i,r in enumerate(results):
        cap+=str(i+1)+". "+r["title"][:55]+"\n"
        if r.get("artist"): cap+="   by "+r["artist"][:30]+"\n"
    cap+="\nPick one:"
    btns=[[{"text":str(i+1)+". "+results[i]["title"][:18],"callback_data":prefix+":"+str(i)}] for i in range(len(results))]
    btns.append([{"text":"❌ Cancel","callback_data":"cancel"}])
    pending[cid]={source.lower():results,"q":title}
    tg_send(cid,cap,buttons=btns)

# ── Callbacks (all answer INSTANTLY then run work in bg) ──────
def cb_pick(cid,idx,qid):
    info=pending.get(cid)
    if not info or idx>=len(info.get("artists",[])): tg_cb(qid,"Expired"); return
    a=info["artists"][idx]; del pending[cid]
    tg_cb(qid,"Selected "+a.get("name","?")[:20])
    threading.Thread(target=lambda: show_confirm(cid,a), daemon=True).start()

def cb_add(cid,parts,qid):
    if cid in pending: del pending[cid]
    tg_cb(qid,"Adding "+parts[2][:20]+"...")
    threading.Thread(target=lambda: do_add(cid,parts[1],parts[2]), daemon=True).start()

def cb_album(cid,parts,qid):
    gid=parts[1]; title=parts[2] if len(parts)>2 else "selected album"
    info=pending.get(cid)
    if not info: tg_cb(qid,"Session expired"); return
    artist=info.get("artists",[{}])[0]; aname=artist.get("name","?")
    lidarr_lookup=lidarr("GET","album/lookup?term="+urllib.parse.quote("lidarr:"+gid))
    lidarr_id=None
    if lidarr_lookup and len(lidarr_lookup)>0:
        lidarr_id=lidarr_lookup[0].get("id")
    tg_cb(qid,"Adding "+title[:20]+"...")
    threading.Thread(target=lambda: do_add(cid,artist.get("id",""),aname,album_ids=[lidarr_id] if lidarr_id else None), daemon=True).start()

def cb_content(cid,parts,qid):
    atype=parts[1]; aname=parts[2] if len(parts)>2 else "?"
    info=pending.get(cid)
    if not info: tg_cb(qid,"Session expired"); return
    artist=info.get("artists",[{}])[0]
    tg_cb(qid,"Loading "+atype+"s...")
    threading.Thread(target=lambda: show_album_list(cid,artist,atype,aname), daemon=True).start()

def cb_back(cid,aname,qid):
    info=pending.get(cid)
    if not info: tg_cb(qid,"Session expired"); return
    artist=info.get("artists",[{}])[0]
    tg_cb(qid,"Back")
    threading.Thread(target=lambda: show_confirm(cid,artist), daemon=True).start()

def cb_yt(cid,query,qid):
    tg_cb(qid,"🔍 Searching..."); msg=tg_send(cid,ICON["youtube"]+" Searching YouTube...")
    threading.Thread(target=lambda: (results:=yt_search(query)) and show_results(cid,query,results,"YouTube","ytdl",yt_download), daemon=True).start()

def cb_ytdl(cid,idx,qid):
    info=pending.get(cid); r=info.get("yt") if isinstance(info,dict) else None
    if not r or idx>=len(r): tg_cb(qid,"Expired"); return
    v=r[idx]; del pending[cid]
    tg_cb(qid,"⏳ Downloading...")
    threading.Thread(target=lambda: yt_download(v["id"],v["title"],cid), daemon=True).start()

def cb_bc(cid,query,qid):
    tg_cb(qid,"Send album URL"); tg_send(cid,ICON["bandcamp"]+" *Bandcamp Download*\n\nPaste a Bandcamp album URL to download as FLAC:\nExample: `https://artist.bandcamp.com/album/album-name`")
    # Store that user wants bandcamp — next message is the URL
    if not hasattr(cb_bc,"_pending"): cb_bc._pending = {}
    cb_bc._pending[str(cid)] = True

def cb_bcdl(cid,idx,qid):
    info=pending.get(cid); r=info.get("bandcamp") if isinstance(info,dict) else None
    if not r or idx>=len(r): tg_cb(qid,"Expired"); return
    v=r[idx]; del pending[cid]
    tg_cb(qid,"⏳ Downloading FLAC...")
    threading.Thread(target=lambda: bc_download(v["url"],v["title"],cid), daemon=True).start()

def cb_sc(cid,query,qid):
    tg_cb(qid,"🔍 Searching...")
    threading.Thread(target=lambda: (r:=sc_search(query)) and show_results(cid,query,r,"SoundCloud","scdl",sc_download), daemon=True).start()

def cb_scdl(cid,idx,qid):
    info=pending.get(cid); r=info.get("soundcloud") if isinstance(info,dict) else None
    if not r or idx>=len(r): tg_cb(qid,"Expired"); return
    v=r[idx]; del pending[cid]
    tg_cb(qid,"⏳ Downloading...")
    threading.Thread(target=lambda: sc_download(v["id"],v["title"],cid), daemon=True).start()

def cb_cancel(cid,qid):
    tg_cb(qid,"Cancelled")
    if cid in pending: del pending[cid]

# ── Library browser callbacks ─────────────────────────────────────
def cb_lib_page(cid,parts,qid):
    pg=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
    tg_cb(qid,"Page "+str(pg+1))
    threading.Thread(target=lambda: show_library(cid,pg), daemon=True).start()

def cb_lib_artist(cid,parts,qid):
    aid=parts[1]
    tg_cb(qid,"Loading artist...")
    threading.Thread(target=lambda: show_library_artist(cid,aid), daemon=True).start()

def cb_lib_album(cid,parts,qid):
    album_id=parts[1]
    tg_cb(qid,"Loading album details...")
    threading.Thread(target=lambda: show_album_detail(cid,album_id), daemon=True).start()

def cb_lib_back(cid,parts,qid):
    tg_cb(qid,"Back")
    threading.Thread(target=lambda: show_library(cid,0), daemon=True).start()

def cb_lib_artist_back(cid,parts,qid):
    tg_cb(qid,"Back")
    threading.Thread(target=lambda: show_library(cid,0), daemon=True).start()

def cb_missing_page(cid,parts,qid):
    pg=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 1
    tg_cb(qid,"Page "+str(pg))
    threading.Thread(target=lambda: show_missing(cid,pg), daemon=True).start()

def cb_missing_search(cid,parts,qid):
    tg_cb(qid,"Searching missing albums...")
    threading.Thread(target=lambda: do_missing_search(cid), daemon=True).start()

def cb_album_search(cid,parts,qid):
    album_id=parts[1]
    tg_cb(qid,"Searching album...")
    threading.Thread(target=lambda: do_album_search(cid,album_id), daemon=True).start()

def cb_album_unmonitor(cid,parts,qid):
    album_id=parts[1]
    tg_cb(qid,"Updating...")
    threading.Thread(target=lambda: do_album_unmonitor(cid,album_id), daemon=True).start()

# ── Status & commands ──────────────────────────────────────────
PER_PAGE = 10

def fmt_size(b):
    for u in ("B","KB","MB","GB","TB"):
        if b<1024: return f"{b:.1f}{u}"
        b/=1024
    return f"{b:.1f}PB"

CMD_HELP = """🎵 *DnD Music Bot — Commands*

🎤 *Add music:*
Just send an artist name or `Artist - Album`
• Searches Soulseek + torrents first
• 🟣 Bandcamp: tap button → paste URL → real FLAC
• 🔴 YouTube / 🟠 SoundCloud fallback

📋 *Library (from Lidarr):*
`/library` — Browse all artists in your collection
`/missing` — Albums still missing / wanted
`/find <name>` — Check if artist is already in your library
`/stats` — Library overview (artists, albums, size)

📋 *Downloads:*
`/status` — Downloads, torrents, disk
`/queue` — Lidarr download queue only
`/recent` — Last 10 imported albums
`/disk` — Disk usage details

🔗 *Services:*
`/lidarr` — Open Lidarr web UI
`/qbit` — Open qBittorrent web UI
`/slskd` — Open slskd web UI
`/prowlarr` — Open Prowlarr web UI
`/restart <service>` — Restart a stack container
`/stack` — All containers status
`/commands` or `/help` — This list
"""

def cmd_help(cid): tg_send(cid,CMD_HELP)

def cmd_queue(cid):
    msg="📥 *Lidarr Queue*\n"
    try:
        q=lidarr("GET","queue?page=1&pageSize=20")
        if q and q.get("records") and len(q["records"])>0:
            for r in q["records"]:
                a=r.get("artist",{}).get("artistName","?")
                b=r.get("album",{}).get("title","?")
                s=r.get("status","?"); p=r.get("progress",0)*100
                msg+="• "+a+" - "+b+" : "+s+" ("+str(int(p))+"%)\n"
        else: msg+="Nothing currently downloading.\n"
    except: msg+="Error fetching queue.\n"
    msg+="\n⚠️ Queue is managed by Lidarr. Items appear when grabbing or importing."
    tg_send(cid,msg)

def cmd_recent(cid):
    msg="📜 *Recently Imported*\n"
    try:
        h=lidarr("GET","history?page=1&pageSize=10&sortKey=date&sortDirection=descending&eventType=1")
        if h and "records" in h and len(h["records"])>0:
            for r in h["records"]:
                aid=r.get("artistId"); bid=r.get("albumId")
                an="?"; bn="?"
                if aid:
                    art=lidarr("GET","artist/"+str(aid))
                    if art: an=art.get("artistName","?")
                if bid:
                    alb=lidarr("GET","album/"+str(bid))
                    if alb: bn=alb.get("title","?")
                d=r.get("date","")[:10] if r.get("date") else "?"
                msg+="• "+an+" - "+bn+" ("+d+")\n"
        else: msg+="No recently imported albums.\n"
    except Exception as e: msg+="Error: "+str(e)[:50]
    tg_send(cid,msg)

def cmd_disk(cid):
    try:
        with open("/downloads/.disk_status") as f:
            line=f.read().strip()
            if line:
                parts=[x for x in line.split() if x]
                if len(parts)>=4:
                    tg_send(cid,"💾 *External SSD (/Volumes/M1)*\nSize: "+parts[1]+"\nUsed: "+parts[2]+"\nFree: "+parts[3]+"\nUsage: "+parts[4])
                    return
    except: pass
    try:
        rf=lidarr("GET","rootFolder")
        if rf and len(rf)>0:
            r=rf[0]
            if r.get("accessible") and "freeSpace" in r:
                fs=r["freeSpace"]; ts=r["totalSpace"]
                free_gb=fs//(1024**3); total_gb=ts//(1024**3); used_gb=total_gb-free_gb
                pct=int((1-fs/ts)*100) if ts>0 else 0
                tg_send(cid,"💾 *Disk: "+r.get("name","?")+"*\nSize: "+str(total_gb)+" GB\nUsed: "+str(used_gb)+" GB\nFree: "+str(free_gb)+" GB ("+str(pct)+"%)")
            else:
                tg_send(cid,"⚠️ Volume inaccessible — run `/restart lidarr` on Mac mini")
        else: tg_send(cid,"❌ No root folder in Lidarr")
    except: tg_send(cid,"❌ Error")

def cmd_lidarr(cid): tg_send(cid,"🔗 *Lidarr*\nhttp://100.101.21.73:8686")
def cmd_qbit(cid): tg_send(cid,"🔗 *qBittorrent*\nhttp://100.101.21.73:8080\nUser: admin | Pass: (set in config)")
def cmd_slskd(cid): tg_send(cid,"🔗 *slskd*\nhttp://100.101.21.73:5030")
def cmd_prowlarr(cid): tg_send(cid,"🔗 *Prowlarr*\nhttp://100.101.21.73:9696")

def cmd_restart(cid, service):
    svc=service.strip().lower()
    valid=["flaresolverr","qbittorrent","prowlarr","lidarr","slskd","soularr","dnd-bot"]
    if svc not in valid: tg_send(cid,"Available: "+", ".join(valid)); return
    tg_send(cid,"🔄 Restarting *"+svc+"*...")
    threading.Thread(target=lambda: (
        subprocess.run(["docker","compose","-f","/Users/dnd/Desktop/MediaStack/docker-compose.yml","restart",svc],capture_output=True,timeout=30),
        time.sleep(5),
        tg_send(cid,"✅ *"+svc+"* restarted!")
    ), daemon=True).start()

def cmd_stack(cid):
    tg_send(cid,"🐳 *Stack containers*\n• flaresolverr\n• qbittorrent\n• prowlarr\n• lidarr\n• slskd\n• soularr\n• dnd-bot\n\nRun `/restart <name>` to restart any.\nFor live status, check the web UIs:\n`/lidarr` `/qbit` `/slskd` `/prowlarr`")

# ── Library browser UI ──────────────────────────────────────────
def show_library(cid,page=0):
    arts=lidarr_artists()
    if not arts: tg_send(cid,"❌ No artists in Lidarr library."); return
    total=len(arts); start=page*PER_PAGE; end=min(start+PER_PAGE,total)
    msg=f"📚 *Your Library ({total} artists)*\n"
    for i in range(start,end):
        a=arts[i]
        n=a.get("artistName","?")[:35]
        s=a.get("statistics",{})
        ac=s.get("albumCount",0); fc=s.get("trackFileCount",0)
        m="🟢" if a.get("monitored") else "🔴"
        msg+=f"\n{m} {i+1}. *{n}* — {ac} albums, {fc} files"
    btns=[]
    if page>0: btns.append({"text":"◀️ Prev","callback_data":f"lib_page:{page-1}"})
    if end<total: btns.append({"text":"Next ▶️","callback_data":f"lib_page:{page+1}"})
    nav_btns=[]
    if btns: nav_btns.append(btns)
    # Add first 5 artists as quick-jump buttons per page
    for i in range(start,end):
        a=arts[i]; label=a.get("artistName","?")[:20]
        nav_btns.append([{"text":label,"callback_data":f"lib_artist:{a.get('id')}"}])
    tg_send(cid,msg,nav_btns)

def show_library_artist(cid,aid):
    a=lidarr("GET","artist/"+str(aid))
    if not a: tg_send(cid,"❌ Artist not found."); return
    aname=a.get("artistName","?")
    albums=lidarr_albums(aid)
    if not albums: tg_send(cid,f"📀 *{aname}*\n\nNo albums found in Lidarr."); return
    # Sort by release date descending
    albums.sort(key=lambda x: x.get("releaseDate","") or "0000", reverse=True)
    msg=f"💿 *{aname}* — {len(albums)} albums\n"
    btns=[]
    for i,al in enumerate(albums[:15]):
        t=al.get("title","?")[:25]
        y=(al.get("releaseDate","") or "")[:4]
        m="🟢" if al.get("monitored") else "🔴"
        st="✅" if al.get("statistics",{}).get("trackFileCount",0)>0 else "⬇️"
        msg+=f"\n{m} {st} {t} ({y})"
        btns.append([{"text":"💿 "+t[:25],"callback_data":f"lib_album:{al.get('id')}"}])
    btns.append([{"text":"🔙 Back to Library","callback_data":"lib_back:0"}])
    tg_send(cid,msg,btns)

def show_album_detail(cid,album_id):
    al=lidarr("GET","album/"+str(album_id))
    if not al: tg_send(cid,"❌ Album not found."); return
    title=al.get("title","?"); aname=al.get("artist",{}).get("artistName","?")
    y=(al.get("releaseDate","") or "")[:4]; genre=al.get("genres",[]) or []
    genre_str=", ".join(g[:12] for g in genre[:3]) if genre else "—"
    monitored=al.get("monitored",False)
    q=get_quality(al)
    stats=al.get("statistics",{})
    tc=stats.get("trackCount",0); fc=stats.get("trackFileCount",0)
    size=stats.get("sizeOnDisk",0)
    # Track listing
    tracks=lidarr_tracks(album_id)
    msg=f"💿 *{title}*\n{aname} ({y})\n━━━━━━━━━━━━━━━━━━━\n"
    msg+=f"🎵 Monitored: {'✅' if monitored else '🔴'} | Genre: {genre_str}\n"
    msg+=f"🎧 Quality: {q} | Tracks: {fc}/{tc}\n"
    if size>0: msg+=f"💾 Size: {fmt_size(size)}\n"
    msg+="\n📜 *Tracklist:*\n"
    if tracks:
        for i,t in enumerate(tracks[:20],1):
            tn=t.get("trackNumber",i); tt=t.get("title","?")[:30]
            has_file="✅" if t.get("trackFile") else "⬇️"
            msg+=f"{has_file} {tn}. {tt}\n"
        if len(tracks)>20: msg+=f"... and {len(tracks)-20} more tracks\n"
    else:
        msg+="No track data available.\n"
    btns=[[{"text":"📥 Search on Lidarr","callback_data":f"album_search:{album_id}"},
            {"text":"👁️ Unmonitor" if monitored else "👁️ Monitor","callback_data":f"album_unmon:{album_id}"}]]
    btns.append([{"text":"🔙 Back to Artist","callback_data":"lib_artist_back:0"}])
    tg_send(cid,msg,btns)

def cmd_library(cid):
    tg_send(cid,"📚 Loading library...")
    threading.Thread(target=lambda: show_library(cid,0), daemon=True).start()

# ── Missing / Wanted ────────────────────────────────────────────
def show_missing(cid,page=1):
    res=lidarr_missing(page)
    records=res.get("records",[])
    total=res.get("totalRecords",0)
    if not records: tg_send(cid,"🎉 No missing albums — library is complete!"); return
    msg=f"⬇️ *Missing Albums ({total} total)* — Page {page}\n\n"
    for i,r in enumerate(records,1):
        an=r.get("artist",{}).get("artistName","?")
        al=r.get("album",{}).get("title","?")
        msg+=f"{i}. *{an}* — {al}\n"
    btns=[[{"text":"📥 Search ALL missing","callback_data":"missing_search:all"}]]
    nav=[]
    if page>1: nav.append({"text":"◀️ Prev","callback_data":f"missing_page:{page-1}"})
    if page*20<total: nav.append({"text":"Next ▶️","callback_data":f"missing_page:{page+1}"})
    if nav: btns.append(nav)
    tg_send(cid,msg,btns)

def do_missing_search(cid):
    tg_send(cid,"⏳ Searching all missing albums...")
    res=lidarr_missing(1,200)
    ids=[r.get("albumId") or r.get("id") for r in res.get("records",[]) if r]
    if not ids: tg_send(cid,"No missing albums to search."); return
    chunk_size=50
    for i in range(0,len(ids),chunk_size):
        chunk=ids[i:i+chunk_size]
        lidarr("POST","command",{"name":"AlbumSearch","albumIds":chunk})
    tg_send(cid,f"✅ Searching {len(ids)} albums! Check `/queue` for progress.")

def cmd_missing(cid):
    tg_send(cid,"⏳ Checking missing albums...")
    threading.Thread(target=lambda: show_missing(cid,1), daemon=True).start()

# ── Find in library ─────────────────────────────────────────────
def cmd_find(cid, name):
    if not name: tg_send(cid,"Usage: `/find Artist Name`"); return
    tg_send(cid,"🔍 Searching your library...")
    threading.Thread(target=lambda: do_find(cid,name), daemon=True).start()

def do_find(cid,name):
    arts=lidarr_artists()
    if not arts: tg_send(cid,"❌ No artists in library."); return
    name_l=name.lower()
    matches=[a for a in arts if name_l in a.get("artistName","").lower()]
    if not matches:
        tg_send(cid,f"❌ *{name}* not found in your library.\nYou can still add it by sending the artist name directly!")
        return
    if len(matches)==1:
        a=matches[0]; n=a.get("artistName","?")
        m="🟢 Monitored" if a.get("monitored") else "🔴 Unmonitored"
        s=a.get("statistics",{})
        msg=f"✅ *{n}* is in your library!\n{m} | {s.get('albumCount',0)} albums | {s.get('trackFileCount',0)} files\n💾 {fmt_size(s.get('sizeOnDisk',0))}"
        btns=[[{"text":"💿 View Albums","callback_data":f"lib_artist:{a.get('id')}"}]]
        tg_send(cid,msg,btns)
        return
    msg=f"🔍 Found {len(matches)} matches for *{name}*:\n"
    btns=[]
    for i,a in enumerate(matches):
        n=a.get("artistName","?")[:30]
        msg+=f"\n{i+1}. {n}"
        btns.append([{"text":n,"callback_data":f"lib_artist:{a.get('id')}"}])
    tg_send(cid,msg,btns)

# ── Stats ───────────────────────────────────────────────────────
def cmd_stats(cid):
    tg_send(cid,"📊 Loading library stats...")
    threading.Thread(target=lambda: do_stats(cid), daemon=True).start()

def do_stats(cid):
    s=lidarr_stats()
    if not s: tg_send(cid,"❌ Could not fetch stats."); return
    msg=f"📊 *Library Stats*\n━━━━━━━━━━━━━━━━━━━\n"
    msg+=f"🎤 Artists: {s['artists']} (🟢 {s['monitored']} monitored)\n"
    msg+=f"💿 Albums: {s['albums']}\n"
    msg+=f"🎵 Tracks: {s['tracks']} ({s['files']} downloaded)\n"
    msg+=f"💾 Total size: {fmt_size(s['size'])}\n"
    pct=int(s['files']/s['tracks']*100) if s['tracks']>0 else 0
    msg+=f"📊 Completion: {pct}%"
    tg_send(cid,msg)

# ── Actions ─────────────────────────────────────────────────────
def do_album_search(cid,album_id):
    r=lidarr("POST","command",{"name":"AlbumSearch","albumIds":[int(album_id)]})
    if r: tg_send(cid,f"✅ Searching album! Check `/queue`.")
    else: tg_send(cid,"❌ Search failed.")

def do_album_unmonitor(cid,album_id):
    al=lidarr("GET","album/"+str(album_id))
    if not al: tg_send(cid,"❌ Album not found."); return
    new_state=not al.get("monitored",True)
    al["monitored"]=new_state
    r=lidarr("PUT",f"album/{album_id}",al)
    if r: tg_send(cid,f"{'🔴 Unmonitored' if not new_state else '🟢 Now monitoring'} album.")
    else: tg_send(cid,"❌ Update failed.")

# ── Messages ────────────────────────────────────────────────────
def handle(cid, text):
    text=text.strip()
    if not text: return
    if text.startswith("/start"):
        tg_send(cid,"🎵 *DnD Music Bot*\n\nSend an artist name like:\n`Miles Davis`\n`Daft Punk`\n\nI'll search Soulseek + torrents first. If not found, I'll offer:\n"+ICON["bandcamp"]+" Bandcamp (real FLAC — paste URL)\n"+ICON["youtube"]+" YouTube\n"+ICON["soundcloud"]+" SoundCloud\n\n`/commands` — Full command list")
        return
    
    # Command routing
    if text.startswith("/"): parts=text[1:].split(" ",1); cmd=parts[0].lower(); arg=parts[1].strip() if len(parts)>1 else ""
    else: cmd=""; arg=""
    
    if cmd in ("help","commands"): cmd_help(cid); return
    elif cmd=="status": cmd_queue(cid); cmd_disk(cid); return
    elif cmd=="queue": cmd_queue(cid); return
    elif cmd=="recent": cmd_recent(cid); return
    elif cmd=="disk": cmd_disk(cid); return
    elif cmd=="lidarr": cmd_lidarr(cid); return
    elif cmd=="qbit": cmd_qbit(cid); return
    elif cmd=="slskd": cmd_slskd(cid); return
    elif cmd=="prowlarr": cmd_prowlarr(cid); return
    elif cmd=="restart": cmd_restart(cid, arg); return
    elif cmd=="stack": cmd_stack(cid); return
    elif cmd=="library": cmd_library(cid); return
    elif cmd=="missing": cmd_missing(cid); return
    elif cmd=="find": cmd_find(cid, arg); return
    elif cmd=="stats": cmd_stats(cid); return
    elif cmd: return  # unknown command, ignore

    # Check if waiting for Bandcamp URL
    waiting = getattr(cb_bc, "_pending", {})
    if waiting.get(str(cid)) and ("bandcamp.com" in text.lower() or "://" in text):
        del waiting[str(cid)]
        tg_send(cid,ICON["bandcamp"]+" Downloading from Bandcamp URL...")
        threading.Thread(target=lambda: bc_download(text.strip(),text.strip().split("/")[-1],cid), daemon=True).start()
        return
    if waiting.get(str(cid)):
        del waiting[str(cid)]
        tg_send(cid,"That doesn't look like a Bandcamp URL. Send a bandcamp.com link!")
        return

    # Send instant acknowledgment then search in bg
    sent = tg_send(cid,"🔍 Searching for *"+text.replace("*","")+"*...")
    
    # Run search in background so bot stays responsive
    def do_search():
        artists=mb_search(text)
        # If not found, try AI silently (no "Did you mean?" message)
        if not artists:
            ai=ai_guess(text)
            if ai and "error" not in ai and ai.get("corrected"):
                artists=mb_search(ai["corrected"])
        if not artists:
            show_platform_picker(cid,text)
            return
        # Pick best match (highest score) and go straight to albums
        best=max(artists, key=lambda a: a.get("score",0))
        show_confirm(cid,best)
    
    threading.Thread(target=do_search, daemon=True).start()

# ── Monitor ─────────────────────────────────────────────────────
def monitor():
    log.info("Download monitor started")
    while True:
        try:
            h=lidarr("GET","history?page=1&pageSize=5&sortKey=date&sortDirection=descending&eventType=1")
            if h and "records" in h:
                for rec in h["records"]:
                    if rec.get("eventType")!=1: continue
                    aid,arid=rec.get("albumId"),rec.get("artistId")
                    if aid and arid and str(arid)+"_"+str(aid) not in notified:
                        album=lidarr("GET","album/"+str(aid)); artist=lidarr("GET","artist/"+str(arid))
                        aname=artist.get("artistName","?") if artist else "?"; title=album.get("title","?") if album else "?"
                        msg="📥 *Download Complete!*\n"+aname+" - "+title
                        for cid in list(notified.keys()): tg_send(cid,msg)
                        notified[str(arid)+"_"+str(aid)]=True
            if len(notified)>500:
                for k in list(notified)[:-200]: del notified[k]
        except Exception as e: log.error("mon: "+str(e))
        time.sleep(60)

# ── Main ────────────────────────────────────────────────────────
def main():
    if not TOKEN or not LIDARR_KEY: log.error("Missing tokens"); sys.exit(1)
    if OR_KEY: log.info("AI enabled")
    log.info("Users: "+( ",".join(ALLOWED) if ALLOWED and ALLOWED!=[""] else "ALL"))
    me=requests.get(TG_API+"/getMe",timeout=10).json()
    log.info("Bot: "+str(me.get("result",{}).get("first_name","?")))
    threading.Thread(target=monitor,daemon=True).start()
    offset=0; hb=0
    while True:
        try:
            r=requests.get(TG_API+"/getUpdates",params={"offset":offset,"timeout":20},timeout=25)
            hb+=1
            if hb%30==0: log.info("Heartbeat: "+str(hb)+" cycles")
            if r.json().get("ok"):
                for u in r.json()["result"]:
                    offset=u["update_id"]+1
                    cb=u.get("callback_query")
                    if cb:
                        cid=cb.get("message",{}).get("chat",{}).get("id",0); data=cb.get("data",""); qid=cb.get("id","")
                        if not allowed(cid): continue
                        pts=data.split(":",2)
                        if data=="cancel": cb_cancel(cid,qid)
                        elif pts[0]=="pick": cb_pick(cid,int(pts[1]),qid)
                        elif pts[0]=="add": cb_add(cid,pts,qid)
                        elif pts[0]=="album": cb_album(cid,pts,qid)
                        elif pts[0]=="content": cb_content(cid,pts,qid)
                        elif pts[0]=="back": cb_back(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="yt": cb_yt(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="ytdl": cb_ytdl(cid,int(pts[1]),qid)
                        elif pts[0]=="bc": cb_bc(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="bcdl": cb_bcdl(cid,int(pts[1]),qid)
                        elif pts[0]=="sc": cb_sc(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="scdl": cb_scdl(cid,int(pts[1]),qid)
                        elif pts[0]=="lib_page": cb_lib_page(cid,pts,qid)
                        elif pts[0]=="lib_artist": cb_lib_artist(cid,pts,qid)
                        elif pts[0]=="lib_album": cb_lib_album(cid,pts,qid)
                        elif pts[0]=="lib_back": cb_lib_back(cid,pts,qid)
                        elif pts[0]=="lib_artist_back": cb_lib_artist_back(cid,pts,qid)
                        elif pts[0]=="missing_page": cb_missing_page(cid,pts,qid)
                        elif pts[0]=="missing_search": cb_missing_search(cid,pts,qid)
                        elif pts[0]=="album_search": cb_album_search(cid,pts,qid)
                        elif pts[0]=="album_unmon": cb_album_unmonitor(cid,pts,qid)
                        continue
                    msg=u.get("message",{}); cid=msg.get("chat",{}).get("id",0)
                    if not allowed(cid): tg_send(cid,"Private bot"); continue
                    notified[cid]=True
                    txt=msg.get("text","").strip()
                    if txt: handle(cid,txt)
            time.sleep(2)
        except requests.exceptions.Timeout: log.warning("Timeout"); time.sleep(1)
        except requests.exceptions.ConnectionError as e: log.error("Reset: "+str(e)[:80]); time.sleep(5)
        except Exception as e: log.error("loop: "+str(e)[:150]); time.sleep(10)

if __name__=="__main__": main()