"""
DG-LAB ESP32 BLE capture web server.
- Reads ESP32 serial (COM4) in a background thread
- Parses DG-LAB V3 commands (B0/BF/BC/50/FF/B1)
- Serves a live web UI at http://127.0.0.1:8765
"""
import os, serial, time, threading, re, json, html, queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
SER_PORT = os.environ.get('DGLAB_SERIAL_PORT', 'COM4')
BAUD = 115200
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dglab_capture.log')

events = []
lock = threading.Lock()
next_id = [1]
subscribers = []          # SSE client queues


def add_event(ev):
    with lock:
        ev['id'] = next_id[0]
        next_id[0] += 1
        events.append(ev)
        if len(events) > 3000:
            del events[:1500]
        payload = json.dumps(ev, ensure_ascii=False)
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            subscribers.remove(q)


def parse_hex(h):
    """Parse a hex command string into a readable description."""
    try:
        b = bytes.fromhex(h)
    except Exception:
        return f"原始: {h}"
    if not b:
        return "空包"
    cmd = b[0]
    if cmd == 0xB0 and len(b) >= 20:
        seq = (b[1] >> 4) & 0xF
        mode = b[1] & 0xF
        mA, mB = (mode >> 2) & 3, mode & 3
        modeName = {0: '不变', 1: '增加', 2: '减少', 3: '绝对值'}
        af = list(b[4:8]); ai = list(b[8:12]); bf = list(b[12:16]); bi = list(b[16:20])
        return (f"⚡刺激 B0 | 序号={seq} A模式={modeName.get(mA,mA)}({b[2]}) B模式={modeName.get(mB,mB)}({b[3]}) "
                f"| A频率{af} A强度{ai} | B频率{bf} B强度{bi}")
    if cmd == 0xBF and len(b) >= 7:
        return f"🔒软限制 BF | A上限={b[1]} B上限={b[2]} | 频率平衡={b[3]},{b[4]} 强度平衡={b[5]},{b[6]}"
    if cmd == 0xBC:
        return f"🌊波形 BC | 数据={h[2:]}"
    if cmd == 0x50:
        return f"⚙️配置 50 | 数据={h[2:]}"
    if cmd == 0x66:
        return f"📋系统配置请求 66"
    if cmd == 0xFF:
        return f"▶️启动 FF"
    if cmd == 0xB1:
        return f"📡强度回报 B1 | A={b[2] if len(b)>2 else '?'} B={b[3] if len(b)>3 else '?'}"
    if cmd == 0x0F:
        return f"🔧命令 0F | 数据={h[2:]}"
    return f"📦命令 {h[:2]} | 数据={h[2:]}"


def parse_wave(h):
    """Extract structured pulse data from a B0 command for the oscilloscope."""
    try:
        b = bytes.fromhex(h)
    except Exception:
        return None
    if len(b) < 20 or b[0] != 0xB0:
        return None
    return {
        'seq': (b[1] >> 4) & 0xF,
        'setA': b[2], 'setB': b[3],
        'aFreq': list(b[4:8]), 'aInt': list(b[8:12]),
        'bFreq': list(b[12:16]), 'bInt': list(b[16:20]),
    }


def classify(line):
    """Turn a serial log line into an event dict."""
    kind = 'log'
    title = line
    detail = ''
    wave = None
    if '[CONNECT]' in line:
        kind = 'connect'
        title = '🔗 设备连接'
    elif '[DISCONNECT]' in line:
        kind = 'disconnect'
        title = '🔌 设备断开'
    elif '[SUB' in line:
        kind = 'sub'
        title = '📢 订阅通知'
    elif '[R ' in line:
        kind = 'read'
        title = '📖 读取特征'
    elif '[WRITE' in line:
        m = re.search(r'\[WRITE\s+(\S+)\].*HEX=([0-9A-Fa-f]+)', line)
        if m:
            kind = 'write'
            title = f"✏️ 写入 {m.group(1)}"
            detail = parse_hex(m.group(2))
            wave = parse_wave(m.group(2)) if detail.startswith('⚡') else None
        else:
            kind = 'write'
            title = '✏️ 写入'
            wave = None
    elif 'NOTIFY' in line:
        m = re.search(r'NOTIFY\s+([0-9A-Fa-f]+)', line)
        kind = 'notify'
        title = '📤 设备通知'
        detail = parse_hex(m.group(1)) if m else line
    ev = {'kind': kind, 'title': title, 'detail': detail,
          'raw': line, 'time': time.strftime('%H:%M:%S')}
    if wave is not None:
        ev['wave'] = wave
    return ev


def serial_reader():
    while True:
        try:
            s = serial.Serial(SER_PORT, BAUD, timeout=1)
            s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False
            s.reset_input_buffer()
            with open(LOG, 'a', encoding='utf-8') as f:
                f.write(f"\n===== web capture start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            while True:
                line = s.readline()
                if not line:
                    continue
                text = line.decode('utf-8', 'replace').rstrip()
                if not text:
                    continue
                ev = classify(text)
                add_event(ev)
                with open(LOG, 'a', encoding='utf-8') as f:
                    f.write(f"[{ev['time']}] {text}\n")
        except Exception as e:
            add_event({'kind': 'error', 'title': '串口错误', 'detail': str(e),
                       'raw': str(e), 'time': time.strftime('%H:%M:%S')})
            time.sleep(2)


HTML_PAGE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DG-LAB ESP32 抓包 · 波形示波器</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;font-family:"Segoe UI","Microsoft YaHei",sans-serif;background:#0b1420;color:#dbe7f3}
  header{padding:14px 22px;background:linear-gradient(135deg,#10243b,#0e1a2b);border-bottom:1px solid #234}
  h1{margin:0;font-size:19px;color:#6fd7ff}
  .sub{font-size:12px;color:#8fa8c0;margin-top:3px}
  .bar{padding:8px 22px;background:#0e1a2b;border-bottom:1px solid #1c2d42;display:flex;gap:9px;align-items:center;flex-wrap:wrap}
  button{background:#1b6ea8;color:#fff;border:0;padding:6px 13px;border-radius:6px;cursor:pointer;font-size:13px}
  button:hover{background:#2487c9}
  .stat{font-size:13px;color:#9fb6cd;margin-left:auto}
  .scope{padding:12px 22px;background:#0a111c;border-bottom:1px solid #1c2d42}
  .scopeHead{display:flex;gap:18px;align-items:center;margin-bottom:8px;font-size:12px;color:#8fa8c0;flex-wrap:wrap}
  .scopeHead b{color:#dbe7f3}
  .legendA{color:#ff9f43}.legendB{color:#4fc3f7}
  .zoomctl{display:inline-flex;gap:3px;align-items:center;color:#8fa8c0}
  .zb{background:#1a3049;color:#9fd0f0;padding:3px 8px;font-size:11px;border-radius:4px;min-width:26px}
  .zb:hover{background:#245078}
  canvas{width:100%;height:230px;background:#060c14;border:1px solid #1c3047;border-radius:6px;display:block}
  .wrap{display:flex;height:calc(100vh - 372px);min-height:200px}
  .list{flex:1;padding:10px 14px 10px 22px;overflow:auto}
  .ev{display:flex;gap:12px;padding:7px 12px;margin:4px 0;border-radius:6px;background:#122034;font-size:13px;border-left:3px solid #2a4a68}
  .ev .t{color:#6c8aa6;font-family:monospace;white-space:nowrap}
  .ev .body{flex:1}
  .ev .title{font-weight:600}
  .ev .detail{color:#7fe0b0;margin-top:3px;font-family:monospace;word-break:break-all}
  .ev .raw{color:#5f7d99;font-size:11px;margin-top:3px;font-family:monospace;word-break:break-all}
  .ev.write{border-left-color:#ffb74d}.ev.notify{border-left-color:#4fc3f7}
  .ev.connect{border-left-color:#81c784}.ev.disconnect{border-left-color:#e57373}
  .ev.sub{border-left-color:#ba68c8}.ev.read{border-left-color:#64b5f6}
  .ev.error{border-left-color:#f44336}
</style>
</head>
<body>
<header><h1>🐋 DG-LAB ESP32 实时抓包 · 波形示波器</h1>
<div class="sub">上方累计时间轴：每条 B0 依次拼接，约 9 秒窗口向左滚动（A橙 / B蓝）· 下方滚动指令</div></header>
<div class="bar">
  <button onclick="location.reload()">🔄 刷新</button>
  <button id="pauseBtn" onclick="togglePause()">⏸ 暂停</button>
  <button onclick="clearScreen()">🗑 清屏</button>
  <span class="stat" id="stat"></span>
</div>
<div class="scope">
  <div class="scopeHead">
    <span class="legendA">■ 通道 A</span><span class="legendB">■ 通道 B</span>
    <span>A设置 <b id="sa">--</b> / B设置 <b id="sb">--</b></span>
    <span>序号 <b id="seq">--</b></span>
    <span>窗口 <b id="winLabel">9.0s</b></span>
    <span class="zoomctl">缩放
      <button class="zb" onclick="setZoom(0.5)">−</button>
      <button class="zb" onclick="setZoom(1)">1×</button>
      <button class="zb" onclick="setZoom(2)">2×</button>
      <button class="zb" onclick="setZoom(4)">4×</button>
      <button class="zb" onclick="setZoom(8)">8×</button>
    </span>
    <span id="waveTime" style="margin-left:auto;color:#5f7d99">等待 B0 指令…</span>
  </div>
  <canvas id="scope"></canvas>
</div>
<div class="wrap"><div class="list" id="list"></div></div>
<script>
let paused=false, lastId=0;
function clearScreen(){
  document.getElementById('list').innerHTML='';
  totalCount=0;
  currentWave=null;
  hist.length=0;
  document.getElementById('waveTime').textContent='等待 B0 指令…';
  drawScope();
  fetch('/clear').then(r=>r.json()).then(j=>{lastId=j.last;});
}
const canvas=document.getElementById('scope'), ctx=canvas.getContext('2d');
let currentWave=null, lastB0Time=0;
const HISTORY=90;            // keep last 90 frames (~9 seconds at 100ms each)
const hist=[];               // each entry: {aFreq,aInt,bFreq,bInt,setA,setB,seq,silent}
const FRAME_MS=100;          // timeline advances one frame every 100ms (real clock)
const SIGNAL_TTL=260;        // if no B0 for this long, draw a flat (silent) frame
let zoom=1;                  // 1 = 9s window; larger = zoom IN (fewer frames shown)
function setZoom(z){
  zoom=z;
  const frames=Math.max(4,Math.round(HISTORY/z));
  document.getElementById('winLabel').textContent=(frames*FRAME_MS/1000).toFixed(1)+'s';
  drawScope();
}

function togglePause(){paused=!paused;document.getElementById('pauseBtn').textContent=paused?'▶ 继续':'⏸ 暂停';}
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// V3 protocol: valid freq byte 10..240, valid intensity 0..100.
// Out-of-range freq (e.g. 0) or intensity >100 (e.g. 101) => channel segment OFF.
function freqValid(f){ return f>=10 && f<=240; }
function intAmp(i){ return i<=100 ? i : 0; }
function pulseCount(f){ return freqValid(f) ? Math.max(1, Math.min(24, Math.round(f/10))) : 0; }

function blankFrame(){
  return {aFreq:[0,0,0,0],aInt:[0,0,0,0],bFreq:[0,0,0,0],bInt:[0,0,0,0],setA:0,setB:0,seq:0,silent:true};
}
// Called every 100ms regardless of signal: timeline keeps scrolling.
function tick(){
  if(paused) return;
  const fresh=(Date.now()-lastB0Time)<SIGNAL_TTL && currentWave;
  const fr=fresh
    ? {aFreq:currentWave.aFreq.slice(),aInt:currentWave.aInt.slice(),
       bFreq:currentWave.bFreq.slice(),bInt:currentWave.bInt.slice(),
       setA:currentWave.setA,setB:currentWave.setB,seq:currentWave.seq,silent:false}
    : blankFrame();
  hist.push(fr);
  if(hist.length>HISTORY) hist.shift();
  const active=hist.filter(h=>!h.silent).length;
  document.getElementById('waveTime').textContent=
    '累计 '+hist.length+' 帧 / '+(hist.length*FRAME_MS/1000).toFixed(1)+'s · 有信号 '+active+' 帧 · '+new Date().toLocaleTimeString();
}
// setWave only updates the latest signal state; tick() does the timeline append.
function setWave(w){
  currentWave=w;
  lastB0Time=Date.now();
  document.getElementById('sa').textContent=w.setA;
  document.getElementById('sb').textContent=w.setB;
  document.getElementById('seq').textContent=w.seq;
}

function drawScope(){
  const dpr=devicePixelRatio;
  const W=canvas.width=canvas.offsetWidth*dpr;
  const H=canvas.height=canvas.offsetHeight*dpr;
  ctx.clearRect(0,0,W,H);
  const PADL=44*dpr, PADB=20*dpr, PADT=4*dpr;   // margins for scales
  const plotW=W-PADL, plotH=H-PADB-PADT;
  // visible frames depend on zoom
  const framesShown=Math.max(4,Math.round(HISTORY/zoom));
  const frameW=plotW/framesShown;
  const visible=Math.min(hist.length,framesShown);
  const startX=PADL+plotW-frameW*visible;  // newest anchored at right

  const aBase=PADT+plotH*0.28, bBase=PADT+plotH*0.76;
  const aAmp=plotH*0.24, bAmp=plotH*0.20;

  // ---- horizontal grid + intensity scale labels ----
  ctx.font=(10*dpr)+'px monospace';ctx.textAlign='right';
  for(const [base,amp,color,label] of [[aBase,aAmp,'#ff9f43','A'],[bBase,bAmp,'#4fc3f7','B']]){
    for(let lv=0;lv<=100;lv+=25){
      const y=base-(lv/100)*amp;
      ctx.strokeStyle='rgba(60,90,125,.25)';ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(PADL,y);ctx.lineTo(W,y);ctx.stroke();
      ctx.fillStyle='#4a6480';ctx.fillText(String(lv),PADL-5*dpr,y+3*dpr);
    }
    ctx.fillStyle=color;ctx.textAlign='left';ctx.fillText(label,4*dpr,base-amp-4*dpr);ctx.textAlign='right';
  }
  // ---- vertical grid + time ticks ----
  ctx.textAlign='center';
  for(let f=0;f<=framesShown;f+=Math.max(1,Math.round(framesShown/9))){
    const x=PADL+plotW-frameW*f;
    ctx.strokeStyle='rgba(60,90,125,.25)';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(x,PADT);ctx.lineTo(x,PADT+plotH);ctx.stroke();
    const secAgo=(f*FRAME_MS/1000);
    ctx.fillStyle='#4a6480';ctx.fillText(secAgo===0?'0s':'-'+secAgo.toFixed(1)+'s',x,H-6*dpr);
  }
  ctx.textAlign='left';

  if(hist.length===0){
    ctx.fillStyle='#4a6480';ctx.font=(13*dpr)+'px sans-serif';
    ctx.fillText('时间轴启动中… 无信号时显示平线，有 B0 时自动绘制波形',PADL+10*dpr,PADT+plotH/2);
    return;
  }
  // ---- draw channels ----
  function drawChannel(chKey,intKey,color,base,amp){
    ctx.strokeStyle=color;ctx.lineWidth=1.3*dpr;ctx.beginPath();
    for(let f=0;f<visible;f++){
      const fr=hist[hist.length-visible+f];
      const freqs=fr[chKey], ints=fr[intKey];
      const x0=startX+f*frameW;
      for(let s=0;s<4;s++){
        const n=pulseCount(freqs[s]);
        const a=(intAmp(ints[s])/100)*amp;
        const segW=frameW/4, segX=x0+s*segW;
        ctx.moveTo(segX,base);
        if(n===0){ctx.lineTo(segX+segW,base);continue;}
        const period=segW/n;
        for(let k=0;k<n;k++){
          const px=segX+k*period;
          const pw=Math.max(0.6*dpr,period*0.2);
          ctx.lineTo(px,base);
          if(a>0){ctx.lineTo(px+pw*0.3,base-a);ctx.lineTo(px+pw*0.7,base-a);}
          ctx.lineTo(px+pw,base);ctx.lineTo(px+period,base);
        }
      }
    }
    ctx.stroke();
  }
  drawChannel('aFreq','aInt','#ff9f43',aBase,aAmp);
  drawChannel('bFreq','bInt','#4fc3f7',bBase,bAmp);
  // "now" marker
  ctx.strokeStyle='rgba(255,255,255,.55)';ctx.lineWidth=1*dpr;
  ctx.beginPath();ctx.moveTo(W-2,0);ctx.lineTo(W-2,PADT+plotH);ctx.stroke();
  ctx.fillStyle='#6c8aa6';ctx.font=(10*dpr)+'px monospace';ctx.textAlign='right';
  ctx.fillText('现在',W-6*dpr,PADT+10*dpr);ctx.textAlign='left';
}

let totalCount=0;
function render(evs){
  const list=document.getElementById('list');
  for(const e of evs){
    if(e.wave) setWave(e.wave);
    const d=document.createElement('div');
    d.className='ev '+e.kind;
    d.setAttribute('data-id', e.id);
    d.innerHTML='<span class="t">'+esc(e.time)+'</span><div class="body"><div class="title">'+esc(e.title)+'</div>'+
      (e.detail?'<div class="detail">'+esc(e.detail)+'</div>':'')+
      '<div class="raw">'+esc(e.raw)+'</div></div>';
    list.appendChild(d);
    totalCount++;
  }
  // keep DOM bounded: drop oldest when too many
  while(list.children.length>1500){list.removeChild(list.firstChild);}
  list.scrollTop=list.scrollHeight;
  document.getElementById('stat').textContent='共 '+totalCount+' 条事件';
}
// SSE: events arrive instantly (no 250ms polling lag)
const es=new EventSource('/stream');
es.onmessage=function(e){
  if(paused)return;
  try{
    const ev=JSON.parse(e.data);
    render([ev]);
    lastId=ev.id;
  }catch(err){}
};
es.onerror=function(){/* auto-reconnect by EventSource */};
setInterval(()=>{tick();},FRAME_MS);          // timeline advances every 100ms, even with no signal
setInterval(()=>{drawScope();},40);           // render at 25fps
// pre-fill the timeline so it's already scrolling on load
for(let i=0;i<HISTORY;i++) tick();
drawScope();
</script>
</body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith('/stream'):
            # SSE: push each new event the instant it arrives
            q = queue.Queue()
            with lock:
                subscribers.append(q)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                # send backlog from last 50 events so page shows recent history
                with lock:
                    backlog = events[-50:]
                for ev in backlog:
                    self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode('utf-8'))
                self.wfile.flush()
                while True:
                    try:
                        payload = q.get(timeout=15)
                        self.wfile.write(f"data: {payload}\n\n".encode('utf-8'))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                with lock:
                    if q in subscribers:
                        subscribers.remove(q)
        elif self.path.startswith('/events'):
            m = re.search(r'since=(\d+)', self.path)
            since = int(m.group(1)) if m else 0
            with lock:
                subset = [e for e in events if e['id'] > since]
                last = events[-1]['id'] if events else since
            data = json.dumps({'events': subset, 'last': last}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == '/clear':
            with lock:
                events.clear()
                cur = next_id[0] - 1
            resp = json.dumps({'last': cur}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
        else:
            data = HTML_PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)


if __name__ == '__main__':
    t = threading.Thread(target=serial_reader, daemon=True)
    t.start()
    print(f"DG-LAB capture web: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
