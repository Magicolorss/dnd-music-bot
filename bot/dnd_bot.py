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
def mb_albums(mbid):
    try:
        r=requests.get("https://musicbrainz.org/ws/2/release-group/",params={"artist":mbid,"fmt":"json","limit":6,"type":"album|ep"},headers={"User-Agent":"DnDBot/1.0"},timeout=15)
        out=[]
        for g in r.json().get("release-groups",[]):
            y=g.get("first-release-date","")[:4] if g.get("first-release-date") else ""
            out.append({"title":g.get("title","?"),"year":y,"id":g.get("id","")})
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
def do_add(cid,mbid,name):
    lookup=lidarr("GET","artist/lookup?term="+urllib.parse.quote("lidarr:"+mbid))
    if lookup and len(lookup)>0 and lookup[0].get("id",0)>0:
        ex=lookup[0]
        if ex.get("monitored"): tg_send(cid,"✅ *"+name+"* already in Lidarr!"); return
        ex["monitored"]=True; ex["addOptions"]={"searchForMissingAlbums":True}
        lidarr("PUT","artist/"+str(ex["id"]),ex); tg_send(cid,"✅ *"+name+"* now monitored! Searching..."); return
    add=lidarr("POST","artist",{"foreignArtistId":mbid,"artistName":name,"monitored":True,"monitorNewItems":"all",
        "rootFolderPath":"/music","qualityProfileId":2,"metadataProfileId":1,"addOptions":{"searchForMissingAlbums":True,"searchForNewAlbums":True}})
    if add: tg_send(cid,"✅ *"+name+"* added! Auto-downloading through Soulseek + torrents...\n📥 Will notify when complete!")
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
    aname=artist.get("name","?"); mbid=artist["id"]; d=artist.get("disambiguation",""); albums=mb_albums(mbid); cover=artist_cover(aname); ai=ai_guess(aname) if OR_KEY else None
    cap=ICON["musicbrainz"]+" *"+aname+"*"+(" ("+d+")" if d else "")
    if ai and ai.get("bio"): cap+="\n\n"+ai["bio"][:300]
    if albums: cap+="\n\n📀 *Albums:*"+ "".join("\n• "+a["title"]+(" ("+a["year"]+")" if a["year"] else "") for a in albums[:5])
    cap+="\n\n*Add to Lidarr and start downloading?*"
    btns=[[{"text":"✅ Yes, download","callback_data":"add:"+mbid+":"+aname}],
           [{"text":ICON["bandcamp"]+" Bandcamp (FLAC)","callback_data":"send:"+aname}],
           [{"text":ICON["youtube"]+" YouTube","callback_data":"yt:"+aname[:40]}],
           [{"text":"❌ Cancel","callback_data":"cancel"}]]
    pending[cid]={"artists":[artist]}
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

# ── Status & commands ──────────────────────────────────────────
CMD_HELP = """🎵 *DnD Music Bot — Commands*

🎤 *Add music:*
Just send an artist name or `Artist - Album`
• Searches Soulseek + torrents first
• 🟣 Bandcamp: tap button → paste URL → real FLAC
• 🔴 YouTube / 🟠 SoundCloud fallback

📋 *Commands:*
`/status` — Downloads, torrents, disk
`/queue` — Lidarr download queue only
`/recent` — Last 10 imported albums
`/disk` — Disk usage details
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
                a=r.get("artist",{}).get("artistName","?") if r.get("artist") else "?"
                b=r.get("album",{}).get("title","?") if r.get("album") else "?"
                d=r.get("date","")[:10] if r.get("date") else "?"
                msg+="• "+a+" - "+b+" ("+d+")\n"
        else: msg+="No recently imported albums.\n"
    except: msg+="Error fetching history.\n"
    tg_send(cid,msg)

def cmd_disk(cid):
    # Try reading real disk info from file written by watchdog
    try:
        with open("/downloads/.disk_status") as f:
            line=f.read().strip()
            if line:
                parts=[x for x in line.split() if x]
                if len(parts)>=4:
                    tg_send(cid,"💾 *External SSD (/Volumes/M1)*\nSize: "+parts[1]+"\nUsed: "+parts[2]+"\nFree: "+parts[3]+"\nUsage: "+parts[4])
                    return
    except: pass
    # Fallback: Lidarr API
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
        if not artists:
            ai=ai_guess(text)
            if ai and "error" not in ai and ai.get("corrected"):
                tg_send(cid,"Did you mean *"+ai["corrected"]+"*?")
                artists=mb_search(ai["corrected"])
        if not artists:
            show_platform_picker(cid,text)
            return
        if len(artists)>1: picker(cid,artists); return
        show_confirm(cid,artists[0])
    
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
                        elif pts[0]=="yt": cb_yt(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="ytdl": cb_ytdl(cid,int(pts[1]),qid)
                        elif pts[0]=="bc": cb_bc(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="bcdl": cb_bcdl(cid,int(pts[1]),qid)
                        elif pts[0]=="sc": cb_sc(cid,pts[1] if len(pts)>1 else "",qid)
                        elif pts[0]=="scdl": cb_scdl(cid,int(pts[1]),qid)
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