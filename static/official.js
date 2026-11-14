(() => {
  "use strict";
  const root = document.documentElement;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const safeScroll = reduced.matches ? "auto" : "smooth";
  const nav = document.getElementById("menu-links");
  const menuButton = document.getElementById("menu-button");
  const closeNav = () => {
    nav?.classList.remove("open");
    menuButton?.setAttribute("aria-expanded", "false");
    menuButton?.setAttribute("aria-label", "Abrir menu");
  };
  menuButton?.addEventListener("click", () => {
    const isOpen = nav?.classList.toggle("open") || false;
    menuButton.setAttribute("aria-expanded", String(isOpen));
    menuButton.setAttribute("aria-label", isOpen ? "Fechar menu" : "Abrir menu");
  });
  nav?.querySelectorAll("a").forEach(link => link.addEventListener("click", closeNav));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeNav();
  });
  document.addEventListener("click", event => {
    if (nav?.classList.contains("open") && !nav.contains(event.target) && !menuButton?.contains(event.target)) closeNav();
  });

  const progress = document.getElementById("scroll-progress");
  let pending = false;
  const updateProgress = () => {
    const remaining = Math.max(0, root.scrollHeight - window.innerHeight);
    if (progress) progress.style.width = ((remaining > 0 ? Math.min(1, window.scrollY / remaining) : 0) * 100).toFixed(1) + "%";
    pending = false;
  };
  const onScroll = () => {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(updateProgress);
  };
  window.addEventListener("scroll", onScroll, {passive:true});
  window.addEventListener("resize", onScroll, {passive:true});
  updateProgress();

  const observerTargets = document.querySelectorAll(".reveal");
  if (!reduced.matches && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    }, {threshold: 0.07, rootMargin:"0px 0px 30px 0px"});
    observerTargets.forEach(el => io.observe(el));
    document.body.classList.add("js-ready");
  } else {
    observerTargets.forEach(el => el.classList.add("visible"));
  }

  const select = document.getElementById("service-select");
  document.querySelectorAll("[data-product]").forEach(link => link.addEventListener("click", () => {
    if (select) select.value = link.getAttribute("data-product") || "";
  }));

  const origin = document.getElementById("origem");
  const params = new URLSearchParams(location.search);
  if (origin) {
    const labels = ["utm_source", "utm_medium", "utm_campaign"]
      .map(k => String(params.get(k) || "").replace(/[^a-z0-9_\- .]/gi, "").slice(0, 38))
      .filter(Boolean);
    origin.value = (labels.length ? "site_oficial_v2|" + labels.join("|") : "site_oficial_v2").slice(0, 180);
  }

  // The format checker reduces test numbers and typos. It does NOT verify ownership.
  const form = document.getElementById("quote-form");
  const phone = form?.querySelector('input[name="whatsapp"]');
  const allowedDDD = new Set([11,12,13,14,15,16,17,18,19,21,22,24,27,28,31,32,33,34,35,37,38,
    41,42,43,44,45,46,47,48,49,51,53,54,55,61,62,63,64,65,66,67,68,69,71,73,74,75,77,79,
    81,82,83,84,85,86,87,88,89,91,92,93,94,95,96,97,98,99]);
  const normalizePhone = (value) => {
    let d=String(value || "").replace(/\D/g,"");
    if (d.length===13 && d.startsWith("55")) d=d.slice(2);
    if (d.length!==11 || !allowedDDD.has(Number(d.slice(0,2))) || d[2]!=="9") return null;
    const sub=d.slice(2);
    if (new Set(sub).size<3 || /^(\d)\1{7}$/.test(sub.slice(1))) return null;
    if (["12345678","87654321","00000000","99999999"].includes(sub.slice(1))) return null;
    return d;
  };
  phone?.addEventListener("input",()=>{
    phone.setCustomValidity("");
    if (phone.value.replace(/\D/g,"").length>13) phone.value=phone.value.slice(0,20);
  });
  form?.addEventListener("submit",event=>{
    const p=phone ? normalizePhone(phone.value) : null;
    if (!p && phone){
      event.preventDefault();
      phone.setCustomValidity("Digite seu celular brasileiro verdadeiro com DDD e nono dígito. Números de exemplo não são aceitos.");
      phone.reportValidity();
      return;
    }
    if (!form.reportValidity()) { event.preventDefault(); return; }
    const submit=form.querySelector(".form-submit");
    if (submit) { submit.disabled=true;submit.textContent="Enviando sua solicitação..."; }
  });

  const video=document.getElementById("showcase-video");
  const toggle=document.getElementById("video-toggle");
  const sound=document.getElementById("showcase-sound");
  if (video) {
    if (reduced.matches) video.pause();
    toggle?.addEventListener("click",()=>{
      if(video.paused)video.play().then(()=>{toggle.textContent="Pausar vídeo";}).catch(()=>{});
      else {video.pause();toggle.textContent="Reproduzir vídeo";}
    });
    sound?.addEventListener("click",()=>{
      video.muted=false;
      video.loop=false;
      video.currentTime=0;
      video.play().then(()=>{sound.textContent="Som ativado";sound.disabled=true;})
        .catch(()=>{sound.textContent="Use o controle de reprodução";});
    });
  }

  // Cookies: a short, accessible preference notice.
  // No analytics/tracking is injected at all. Only the CSRF session cookie is essential.
  const cookieNotice=document.getElementById("cookie-notice");
  const cookieSettings=document.getElementById("cookie-settings");
  const cookieKey="gtech_cookie_preference_v1";
  const hasCookieChoice=()=>{
    try {
      const saved=JSON.parse(localStorage.getItem(cookieKey)||"null");
      return !!(saved&&["essential","all"].includes(saved.choice)&&
               Number.isFinite(saved.at)&&Date.now()-saved.at<180*86400000);
    } catch (_) {return false;}
  };
  const showCookieNotice=()=>{if(cookieNotice) cookieNotice.hidden=false;};
  const hideCookieNotice=()=>{if(cookieNotice) cookieNotice.hidden=true;};
  if (!hasCookieChoice()) showCookieNotice();
  cookieNotice?.querySelectorAll("[data-cookie-choice]").forEach(button=>
    button.addEventListener("click",()=>{
      const choice=button.getAttribute("data-cookie-choice");
      if(!["essential","all"].includes(choice))return;
      try{localStorage.setItem(cookieKey,JSON.stringify({choice,at:Date.now()}));}catch(_){}
      hideCookieNotice();
    }));
  cookieSettings?.addEventListener("click",showCookieNotice);

  // Original G Tech shield and lettering break apart into atomic particles.
  const introTemplate = document.getElementById("gtech-intro-template");
  const replay = document.getElementById("gtech-intro-replay");
  let activeIntro = null;
  const introDuration = 3400;
  function playGtechIntro(force = false) {
    if (!introTemplate || activeIntro) return;
    const overlay = introTemplate.content.firstElementChild.cloneNode(true);
    document.body.appendChild(overlay);
    activeIntro = overlay;
    const canvas = overlay.querySelector("#gtech-intro-canvas");
    const ctx = canvas.getContext("2d", {alpha: false});
    const center = overlay.querySelector(".intro-center");
    const logo = overlay.querySelector("#gtech-intro-logo");
    const skip = overlay.querySelector("#gtech-intro-skip");
    const progress = overlay.querySelector("#gtech-intro-progress");
    const previousFocus = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    skip.focus({preventScroll:true});
    let w=0,h=0,dpr=1,raf=0,started=performance.now(),stopped=false;
    const seedRand = (seed) => {
      let x=seed;
      return () => {x = (x * 1664525 + 1013904223) >>> 0; return x / 4294967296;};
    };
    const random=seedRand(1342);
    const stars = Array.from({length:innerWidth<680?90:160},()=>({
      x:random(),y:random(),r:random()*1.2+.2,p:random()*Math.PI*2
    }));
    let dots=[];
    const fit = () => {
      w=Math.max(1,window.innerWidth);h=Math.max(1,window.innerHeight);
      dpr=Math.min(2,window.devicePixelRatio||1);
      canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);
    };
    fit();
    const sampleLogo = () => {
      const out=[];
      const size=280;
      const off=document.createElement("canvas");off.width=size;off.height=size;
      const c=off.getContext("2d",{willReadFrequently:true});
      const display=Math.min(w<680 ? w*.92 : w*.74, w<680 ? 350 : 530);
      const scale=display/size;
      try {
        // Sample the exact official logo, including its custom G Tech lettering.
        // The white document background is ignored, never shattered into particles.
        c.drawImage(logo,0,0,size,size);
        const px=c.getImageData(0,0,size,size).data;
        const step=w<680?6:5;
        for(let y=0;y<size;y+=step)for(let x=0;x<size;x+=step){
          const i=(y*size+x)*4, r=px[i],g=px[i+1],b=px[i+2];
          const light=Math.min(r,g,b);
          if(px[i+3]<100||light>242||random()<.14)continue;
          const a=random()*Math.PI*2;
          const speed=85+random()*Math.min(w,h)*.56;
          out.push({
            x:(x-size/2)*scale,y:(y-size/2)*scale,
            dx:Math.cos(a)*speed,dy:Math.sin(a)*speed,
            size:(random()*1.7+1.2)*(w<680?.9:1.15),
            r:Math.min(255,r+18),g:Math.min(255,g+24),b:Math.min(255,b+29)
          });
        }
      }catch(_){}
      if(out.length<120){
        for(let i=0;i<650;i++){
          const a=random()*Math.PI*2,rad=Math.sqrt(random())*Math.min(w*.27,180);
          out.push({x:Math.cos(a)*rad,y:Math.sin(a)*rad,
                    dx:Math.cos(a)*(85+random()*300),dy:Math.sin(a)*(85+random()*300),
                    size:1+random()*2,r:48,g:190,b:236});
        }
      }
      dots=out;
    };
    if(logo.complete && logo.naturalWidth)sampleLogo();
    else logo.addEventListener("load",sampleLogo,{once:true});
    const onResize=()=>fit();window.addEventListener("resize",onResize,{passive:true});
    const onKey=(e)=>{if(e.key==="Escape"||e.key==="Enter"&&document.activeElement===skip){e.preventDefault();dismiss();}};
    window.addEventListener("keydown",onKey);
    function dismiss(){
      if(stopped)return;stopped=true;
      // Do not remember the intro: run it at the start of each new page load.
      window.cancelAnimationFrame(raf);
      window.removeEventListener("keydown",onKey);
      window.removeEventListener("resize",onResize);
      overlay.classList.add("intro-out");
      document.body.style.overflow=priorOverflow;
      window.setTimeout(()=>{overlay.remove();activeIntro=null;previousFocus?.focus?.({preventScroll:true});},650);
    }
    skip.addEventListener("click",dismiss,{once:true});
    if (reduced.matches) {window.setTimeout(dismiss,1050);return;}
    const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
    const draw=(now)=>{
      if(stopped)return;
      const elapsed=now-started;const t=elapsed/introDuration;
      progress.style.width=Math.min(100,t*100)+"%";
      ctx.fillStyle="#030812";ctx.fillRect(0,0,w,h);
      const cx=w/2,cy=h*.5;
      // Film-title stars + subtle central bloom
      const bloom=ctx.createRadialGradient(cx,cy,12,cx,cy,Math.max(w,h)*.62);
      bloom.addColorStop(0,"rgba(20,74,136,.22)");bloom.addColorStop(.37,"rgba(13,35,82,.12)");bloom.addColorStop(1,"rgba(2,4,9,0)");
      ctx.fillStyle=bloom;ctx.fillRect(0,0,w,h);
      for(const star of stars){
        const flicker=.18+.55*(.5+.5*Math.sin(now*.001+star.p));
        ctx.beginPath();ctx.arc(star.x*w,star.y*h,star.r,0,Math.PI*2);
        ctx.fillStyle="rgba(166,211,255,"+flicker.toFixed(3)+")";ctx.fill();
      }
      // Atomic orbits: original geometry, evolving independently of logo pixels.
      const atomA=smoothstep(0,.13,t)*(1-smoothstep(.67,.94,t));
      const radius=Math.min(w*.4,h*.48,300)*(.75+.14*Math.sin(now*.00038));
      ctx.save();ctx.translate(cx,cy);ctx.rotate(-.16);
      for(let k=0;k<3;k++){
        ctx.save();ctx.rotate((Math.PI/3)*k+now*.00011*(k%2?1:-1));
        ctx.beginPath();ctx.ellipse(0,0,radius,radius*.27,0,0,Math.PI*2);
        ctx.lineWidth=1.25;ctx.strokeStyle="rgba("+(k===1?"154,118,255":"63,198,254")+","+(atomA*.27).toFixed(3)+")";ctx.stroke();
        const theta=now*.0007*(k===1?-1:1)+k*1.8;
        const ex=Math.cos(theta)*radius,ey=Math.sin(theta)*radius*.27;
        const grad=ctx.createRadialGradient(ex,ey,0,ex,ey,11);
        grad.addColorStop(0,"rgba(220,250,255,"+atomA+")");grad.addColorStop(1,"rgba(40,174,255,0)");
        ctx.fillStyle=grad;ctx.beginPath();ctx.arc(ex,ey,11,0,Math.PI*2);ctx.fill();
        ctx.restore();
      }
      ctx.restore();
      const burst=smoothstep(.39,.73,t);
      if(t>.41)center.classList.add("fragmented");
      if(dots.length){
        ctx.save();ctx.globalCompositeOperation="screen";
        for(let i=0;i<dots.length;i++){
          const p=dots[i], theta=burst*burst;
          const px=cx+p.x*(1+.25*burst)+p.dx*theta;
          const py=cy+p.y*(1+.25*burst)+p.dy*theta;
          const opacity=Math.min(1,(.52+.48*burst)*(1-smoothstep(.84,.99,t)));
          const size=p.size*(.9+burst*.7);
          ctx.fillStyle="rgba("+Math.min(255,p.r+38)+","+Math.min(255,p.g+40)+","+Math.min(255,p.b+44)+","+opacity.toFixed(3)+")";
          ctx.fillRect(px,py,size,size);
          if(burst>.08 && i%5===0){
            ctx.strokeStyle="rgba(99,215,255,"+(opacity*.7).toFixed(3)+")";
            ctx.lineWidth=1.35;
            ctx.beginPath();ctx.moveTo(px-p.dx*.055*burst,py-p.dy*.055*burst);
            ctx.lineTo(px,py);ctx.stroke();
          }
        }
        ctx.restore();
      }
      if(t>.46&&t<.86){
        const shock=smoothstep(.46,.8,t);
        ctx.beginPath();ctx.arc(cx,cy,shock*Math.max(w,h)*.5,0,Math.PI*2);
        ctx.strokeStyle="rgba(101,205,255,"+((1-shock)*.75).toFixed(3)+")";ctx.lineWidth=2;ctx.stroke();
      }
      if(elapsed>=introDuration){dismiss();return;}
      raf=window.requestAnimationFrame(draw);
    };
    raf=window.requestAnimationFrame(draw);
  }
  if(replay)replay.addEventListener("click",()=>playGtechIntro(true));
  if(document.readyState==="complete"){window.requestAnimationFrame(()=>playGtechIntro(false));}
  else window.addEventListener("load",()=>playGtechIntro(false),{once:true});
})();
