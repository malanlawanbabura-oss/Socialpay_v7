// SocialPay v3.0 UPGRADED

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js').catch(()=>{}));
}

let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredPrompt = e;
  const shown = sessionStorage.getItem('pwa_shown');
  if (!shown) setTimeout(() => {
    const b = document.getElementById('pwa-banner');
    if (b) { b.style.display = 'flex'; sessionStorage.setItem('pwa_shown','1'); }
  }, 4000);
});
function installPWA() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  deferredPrompt.userChoice.then(() => { deferredPrompt = null; dismissPWA(); });
}
function dismissPWA() { const b=document.getElementById('pwa-banner'); if(b) b.style.display='none'; }

function showToast(msg, type='info') {
  const icons = {success:'✅',error:'❌',info:'ℹ️',warning:'⚠️'};
  let c = document.getElementById('toast-container');
  if (!c) { c=document.createElement('div'); c.id='toast-container'; c.className='toast-container'; document.body.appendChild(c); }
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${icons[type]||'•'}</span><span>${msg}</span>`;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transform='translateY(20px)'; t.style.transition='all .3s'; setTimeout(()=>t.remove(),320); }, 3400);
}

function openModal(id) { const el=document.getElementById(id); if(el){el.classList.add('active');document.body.style.overflow='hidden';} }
function closeModal(id) { const el=document.getElementById(id); if(el){el.classList.remove('active');document.body.style.overflow='';} }
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) { e.target.classList.remove('active'); document.body.style.overflow=''; }
});

async function postForm(url, fd, btn) {
  const orig = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled=true; btn.innerHTML='<span class="spinner"></span>'; }
  try {
    const res = await fetch(url, {method:'POST', body:fd});
    const data = await res.json();
    if (data.success) {
      if (data.message) showToast(data.message,'success');
      if (data.redirect) setTimeout(()=>location.href=data.redirect, 700);
    } else { showToast(data.message||'Error','error'); }
    return data;
  } catch(e) { showToast('Network error. Check connection.','error'); return null; }
  finally { if(btn){btn.disabled=false;btn.innerHTML=orig;} }
}

let balHidden = false;
function toggleBalance() {
  balHidden = !balHidden;
  document.querySelectorAll('.balance-amount,.chip-value').forEach(el=>el.style.filter=balHidden?'blur(10px)':'none');
  const eb = document.getElementById('eyeBtn');
  if (eb) eb.textContent = balHidden ? '🙈' : '👁️';
}

function copyText(text, msg) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(()=>showToast(msg||'Copied!','success'));
  } else {
    const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    showToast(msg||'Copied!','success');
  }
}

async function lookupUser(uid, targetId) {
  const el=document.getElementById(targetId);
  if (!uid||uid.length<5){if(el)el.textContent='';return;}
  try {
    const res=await fetch('/api/user_lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid})});
    const data=await res.json();
    if(el){el.textContent=data.found?`✅ ${data.name}`:'❌ Not found';el.style.color=data.found?'#06D6A0':'#EF233C';}
  } catch {}
}

async function updateNotifBadge() {
  try {
    const res=await fetch('/api/notif_count'); const data=await res.json();
    const el=document.getElementById('notif-badge');
    if(el){if(data.count>0){el.textContent=data.count>9?'9+':data.count;el.style.display='flex';}else{el.style.display='none';}}
  } catch {}
}
if (document.getElementById('notif-badge')) { updateNotifBadge(); setInterval(updateNotifBadge,30000); }

document.addEventListener('DOMContentLoaded', () => {
  const path = location.pathname;
  document.querySelectorAll('.nav-item').forEach(item => {
    const href = item.getAttribute('href');
    if (href&&path===href) item.classList.add('active');
    else if (href&&href!=='/'&&path.startsWith(href)) item.classList.add('active');
  });
});

function togglePw(inputId, btn) {
  const inp=document.getElementById(inputId); if(!inp) return;
  if (inp.type==='password'){inp.type='text';btn.innerHTML='🙈';}
  else{inp.type='password';btn.innerHTML='👁️';}
}

function openImageFull(src) {
  let overlay=document.getElementById('img-modal-overlay');
  if (!overlay) {
    overlay=document.createElement('div'); overlay.id='img-modal-overlay'; overlay.className='img-modal-overlay';
    overlay.innerHTML=`<button class="img-modal-close" onclick="closeImageFull()">✕</button><img id="img-modal-img" src="" alt="Proof" onclick="event.stopPropagation()" style="max-width:100%;max-height:90vh;border-radius:12px">`;
    overlay.addEventListener('click',closeImageFull); document.body.appendChild(overlay);
  }
  document.getElementById('img-modal-img').src=src;
  overlay.classList.add('active'); document.body.style.overflow='hidden';
}
function closeImageFull() {
  const o=document.getElementById('img-modal-overlay'); if(o){o.classList.remove('active');document.body.style.overflow='';}
}

function openTelegram(tgUrl, webUrl) {
  const start=Date.now(); window.location.href=tgUrl;
  const timer=setTimeout(()=>{ if(Date.now()-start<2000) window.location.href=webUrl||'https://telegram.org/'; },1500);
  document.addEventListener('visibilitychange',function h(){if(document.hidden){clearTimeout(timer);document.removeEventListener('visibilitychange',h);}});
}

function closeBanner(){document.getElementById('announceWrap')?.remove();document.getElementById('bannerSpacer')?.remove();sessionStorage.setItem('sp_bc','1');}
if(sessionStorage.getItem('sp_bc')){document.getElementById('announceWrap')?.remove();document.getElementById('bannerSpacer')?.remove();}

// ============================================================
// SPIN WHEEL — Fixed v7
// Pointer (▼) is at TOP = -Math.PI/2
// Wheel slots are drawn starting from rotation offset
// winIdx from server = exact prize index that was credited
// Wheel always stops with that exact slot under the pointer
// Numbers on wheel update whenever admin changes prizes
// ============================================================
const SPIN_COLORS=['#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7','#DDA0DD','#98D8C8','#F7DC6F'];
let spinRunning=false;
let _currentRotation=0; // track rotation globally so re-spins continue smoothly

function initSpinWheel(prizes) {
  const canvas=document.getElementById('spin-canvas'); if(!canvas) return;
  const ctx=canvas.getContext('2d');
  const W=canvas.width=260; const H=canvas.height=260;
  const cx=W/2, cy=H/2, r=cx-8;
  const n=prizes.length;
  const arc=(Math.PI*2)/n;

  function drawWheel(rot) {
    ctx.clearRect(0,0,W,H);
    // Draw outer ring
    ctx.beginPath(); ctx.arc(cx,cy,r+6,0,Math.PI*2);
    ctx.fillStyle='#0A2463'; ctx.fill();

    prizes.forEach((p,i) => {
      const s=rot+i*arc;
      const e=s+arc;
      // Slice
      ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,r,s,e); ctx.closePath();
      ctx.fillStyle=SPIN_COLORS[i%SPIN_COLORS.length]; ctx.fill();
      ctx.strokeStyle='white'; ctx.lineWidth=2.5; ctx.stroke();
      // Label — show the prize label (e.g. ₦100) from server prizes
      ctx.save();
      ctx.translate(cx,cy);
      ctx.rotate(s+arc/2);
      // Prize amount text — right-aligned toward edge
      ctx.textAlign='right';
      ctx.fillStyle='white';
      ctx.font='bold 12px Nunito,Arial';
      ctx.shadowColor='rgba(0,0,0,0.4)';
      ctx.shadowBlur=3;
      ctx.fillText(p.label, r-10, 5);
      ctx.restore();
    });

    // Center circle
    ctx.beginPath(); ctx.arc(cx,cy,26,0,Math.PI*2);
    ctx.fillStyle='white'; ctx.fill();
    ctx.beginPath(); ctx.arc(cx,cy,20,0,Math.PI*2);
    ctx.fillStyle='#0A2463'; ctx.fill();
    ctx.fillStyle='white'; ctx.font='bold 11px Arial';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.shadowBlur=0;
    ctx.fillText('SP',cx,cy);
  }

  drawWheel(_currentRotation);

  // _spinWheel(winIdx, cb)
  // winIdx = the prize index the SERVER already credited to user
  // We rotate wheel so that slot winIdx ends up under the TOP pointer (▼)
  window._spinWheel=function(winIdx, cb) {
    if(spinRunning) return;
    spinRunning=true;

    // The pointer is at the TOP of the canvas = angle -Math.PI/2 (i.e. 270°)
    // Slot i occupies angles: [rotation + i*arc, rotation + (i+1)*arc]
    // Center of slot i is at: rotation + i*arc + arc/2
    // We want: rotation + winIdx*arc + arc/2 ≡ -Math.PI/2  (mod 2π)
    // So: targetRotation = -Math.PI/2 - winIdx*arc - arc/2

    const pointerAngle = -Math.PI/2; // top of wheel
    // Desired final rotation so winIdx slot center is at pointer
    const slotCenter = winIdx * arc + arc/2;
    const rawTarget = pointerAngle - slotCenter;
    // Normalise to [0, 2π)
    const normalised = ((rawTarget % (Math.PI*2)) + Math.PI*2) % (Math.PI*2);
    // Add multiple full spins (5-8) for visual effect, landing on exact spot
    const fullSpins = (5 + Math.floor(Math.random()*4)) * Math.PI*2;
    const currentNorm = ((_currentRotation % (Math.PI*2)) + Math.PI*2) % (Math.PI*2);
    // Extra to rotate from current normalised position to target
    let extra = normalised - currentNorm;
    if(extra <= 0) extra += Math.PI*2;
    const totalRotation = fullSpins + extra;

    const duration=4500;
    const startTime=performance.now();
    const startRot=_currentRotation;

    function animate(now) {
      const elapsed=now-startTime;
      const prog=Math.min(elapsed/duration, 1);
      // Ease out cubic — smooth deceleration
      const ease=1-Math.pow(1-prog, 4);
      _currentRotation=startRot+totalRotation*ease;
      drawWheel(_currentRotation);
      if(prog<1) {
        requestAnimationFrame(animate);
      } else {
        _currentRotation=startRot+totalRotation; // set exact final value
        drawWheel(_currentRotation);
        spinRunning=false;
        if(cb) cb();
      }
    }
    requestAnimationFrame(animate);
  };
}

async function doSpin(prizes) {
  const btn=document.getElementById('spin-btn');
  if(spinRunning) return;
  const cost=(typeof SPIN_COST!=='undefined')?SPIN_COST:50;
  if(btn){btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Spinning...';}

  const fd=new FormData();
  const res=await postForm('/spin',fd,null);

  if(res && res.success!==undefined) {
    // Re-init wheel with latest prizes from server (in case admin changed them)
    const serverPrizes=(res.prizes&&res.prizes.length>0)?res.prizes:prizes;
    initSpinWheel(serverPrizes);

    // winIdx = exact index the server credited — wheel MUST stop here
    const winIdx=res.index!==undefined?res.index:0;

    window._spinWheel&&window._spinWheel(winIdx,()=>{
      setTimeout(()=>{
        if(btn){btn.disabled=false;btn.innerHTML='🎰 Spin Now!';}
        // Show the EXACT prize that server credited
        if(res.amount>0) {
          showToast(`🎉 You won ${res.prize}! +₦${res.amount.toLocaleString()}`, 'success');
        } else {
          showToast(`😔 Try Again! ₦${cost.toLocaleString()} spent.`, 'info');
        }
        // Reload after toast so balance updates
        setTimeout(()=>location.reload(), 2800);
      }, 600);
    });
  } else {
    if(btn){btn.disabled=false;btn.innerHTML='🎰 Spin Now!';}
  }
}

function toggleWdFields() {
  const c=document.getElementById('wd-curr')?.value; if(!c) return;
  document.getElementById('naira-banks').style.display=c==='naira'?'':'none';
  document.getElementById('crypto-banks').style.display=c==='dollar'?'':'none';
}
function onBankSel(){document.getElementById('bank-other-wrap').style.display=document.getElementById('wd-bank-sel')?.value==='OTHER'?'':'none';}
function onCryptoSel(){document.getElementById('crypto-other-wrap').style.display=document.getElementById('wd-crypto-sel')?.value==='OTHER'?'':'none';}
function buildBankInfo() {
  const c=document.getElementById('wd-curr')?.value;
  if(c==='naira'){
    const sel=document.getElementById('wd-bank-sel')?.value;
    const bank=sel==='OTHER'?document.getElementById('wd-bank-other')?.value.trim():sel;
    const acct=document.getElementById('wd-acct')?.value.trim();
    const nm=document.getElementById('wd-aname')?.value.trim();
    if(!bank||!acct||!nm){showToast('Fill all bank details','warning');return null;}
    return `Bank: ${bank}\nAccount: ${acct}\nName: ${nm}`;
  } else {
    const sel=document.getElementById('wd-crypto-sel')?.value;
    const w=sel==='OTHER'?document.getElementById('wd-crypto-other')?.value.trim():sel;
    const addr=document.getElementById('wd-addr')?.value.trim();
    const net=document.getElementById('wd-net')?.value;
    if(!w||!addr){showToast('Fill wallet details','warning');return null;}
    return `Wallet: ${w}\nAddress: ${addr}\nNetwork: ${net}`;
  }
}
async function doWithdraw() {
  const bi=buildBankInfo(); if(!bi) return;
  const pin=document.getElementById('wd-pin')?.value||'';
  if(!pin||pin.length!==4){showToast('Please enter your 4-digit PIN','warning');return;}
  const fd=new FormData();
  fd.append('currency',document.getElementById('wd-curr').value);
  fd.append('amount',document.getElementById('wd-amt').value);
  fd.append('bank_info',bi);
  fd.append('pin',pin);
  const r=await postForm('/withdraw',fd,document.getElementById('wd-btn'));
  if(r?.success){closeModal('withdrawModal');setTimeout(()=>location.reload(),1400);}
}
async function doTransfer() {
  const fd=new FormData();
  fd.append('receiver_id',document.getElementById('tr-recv')?.value.trim());
  fd.append('amount',document.getElementById('tr-amt')?.value);
  fd.append('pin',document.getElementById('tr-pin')?.value);
  const r=await postForm('/transfer',fd,document.getElementById('tr-btn'));
  if(r?.success){closeModal('transferModal');setTimeout(()=>location.reload(),1400);}
}
async function doExchange() {
  const fd=new FormData();
  fd.append('from_currency',document.getElementById('ex-from')?.value);
  fd.append('amount',document.getElementById('ex-amt')?.value);
  const r=await postForm('/exchange',fd,document.getElementById('ex-btn'));
  if(r?.success){
    const prev=document.getElementById('ex-preview');
    if(prev) prev.style.display='none';
    closeModal('exchangeModal');
    setTimeout(()=>location.reload(),1400);
  }
}
