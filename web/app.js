const stages=[["01","Intent","Agent requests a service","▤"],["02","Quote","Get price and allowed scope","⌘"],["03","Authority","Verify policy and limits","⬡"],["04","Settlement","USDC transaction on Base","≋"],["05","Execution","Service runs in boundary","</>"],["06","Observation","Independent verification","◉"],["07","Proof","Get verifiable evidence","#"]];
let currentProof=null;
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=20)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};
function draw(mode="idle",upto=99){
 $("#timeline").innerHTML=stages.map((s,i)=>{let c="step";if(mode==="ok"&&i<=upto)c+=" pass";if(mode==="deny"){if(i<2)c+=" pass";else if(i===2)c+=" denied"}return '<article class="'+c+'" data-stage="'+i+'"><div class="step-icon">'+s[3]+'</div><small>['+s[0]+']</small><b>'+s[1]+'</b><p>'+s[2]+'</p></article>'}).join("");
 const proof=document.querySelector('.step[data-stage="6"]');if(proof&&currentProof)proof.onclick=openEvidence
}
draw();
async function run(amount){
 document.body.classList.add("running");draw();
 try{
  const r=await fetch("/api/run",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({amount_atomic:amount,document:"Autonomous agents can purchase digital services. AgentPay Proof constrains payment authority and independently verifies the outcome. Evidence should not depend on the purchasing agent's own claims."})});
  const d=await r.json();if(!r.ok)throw new Error(d.error||"request failed");currentProof=d.proof;const denied=d.status==="DENIED";
  if(denied){draw("deny")}else{for(let i=0;i<7;i++){draw("ok",i);await new Promise(resolve=>setTimeout(resolve,115))}}
  const list=$("#activity-list"),row=document.createElement("p");row.innerHTML='<i class="'+(denied?"bad":"ok")+'"></i><b>AgentPay Demo</b><em>'+(denied?"Denied (policy)":"Verified")+'</em><span>'+(denied?"—":"0.25 USDC")+'</span><small>now</small>';list.prepend(row);while(list.children.length>5)list.lastElementChild.remove()
 }catch(e){console.error(e)}finally{document.body.classList.remove("running")}
}
function openEvidence(){
 if(!currentProof)return;const p=currentProof,rows=[["Intent",p.intent?.intent_id],["Quote",p.quote?.quote_id],["Authority",p.authority?.decision],["Settlement",p.settlement?.transaction_hash],["Execution",p.result?.result_digest],["Observation",p.observation?.observer_id],["Proof",p.proof_hash]];
 $("#evidence-grid").innerHTML=rows.filter(x=>x[1]).map(x=>'<article><small>'+esc(x[0])+'</small><div>'+esc(short(x[1],22))+'</div></article>').join("");$("#evidence-json").textContent=JSON.stringify(p,null,2);$("#evidence-dialog").showModal()
}
$("#run-ok").onclick=()=>run(250000);
$("#explore").onclick=()=>document.querySelector(".services").animate([{boxShadow:"0 0 0 rgba(21,151,255,0)"},{boxShadow:"0 0 42px rgba(21,151,255,.42)"},{boxShadow:"0 0 0 rgba(21,151,255,0)"}],{duration:900});

(()=>{
 const c=$("#scene"),g=c.getContext("2d",{alpha:false});
 let w=0,h=0,dpr=1,start=performance.now(),bits=[],dust=[],mountain=[];
 const rand=i=>{const n=Math.sin(i*127.13+41.7)*43758.5453123;return n-Math.floor(n)};
 function resize(){
  dpr=Math.min(devicePixelRatio||1,2);w=innerWidth;h=innerHeight;c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);c.style.width=w+"px";c.style.height=h+"px";g.setTransform(dpr,0,0,dpr,0,0);
  bits=Array.from({length:520},(_,i)=>({base:rand(i)*(w+360)-180,lane:(rand(i+500)-.5)*210,speed:28+rand(i+900)*115,size:.45+rand(i+1200)*1.65,phase:rand(i+1600)*6.283,tone:rand(i+2000)}));
  dust=Array.from({length:1100},(_,i)=>({x:rand(i+2400)*w,y:rand(i+3300)*h*.72,a:.04+rand(i+4200)*.46,size:.35+rand(i+5100)*1.55}));
  mountain=Array.from({length:350},(_,i)=>({x:i/349*w,y:rand(i+6200),j:rand(i+7100)}));
 }
 function riverY(x,t,lane=0){return h*.43+Math.sin(x*.006+t*.00034)*45+Math.sin(x*.014-t*.00018)*15+lane}
 function ridgeY(x,layer,t){const center=h*(.285+layer*.035);return center+Math.sin(x*.0065+layer*1.9+t*.00007)*25+Math.sin(x*.017-layer*.7)*9+layer*2}
 function drawTerrain(now){
  const fill=g.createLinearGradient(0,h*.18,0,h*.56);fill.addColorStop(0,"rgba(27,102,165,.02)");fill.addColorStop(1,"rgba(4,31,55,.24)");
  for(let layer=6;layer>=0;layer--){g.beginPath();g.moveTo(180,h*.57);for(let x=180;x<w+20;x+=10)g.lineTo(x,ridgeY(x,layer,now));g.lineTo(w+20,h*.57);g.closePath();g.fillStyle=fill;g.fill();g.strokeStyle="rgba(62,143,210,"+(0.08+layer*.014)+")";g.lineWidth=.7;g.stroke()}
  for(const p of mountain){const x=p.x;if(x<180)continue;const y=h*.24+Math.sin(x*.0076)*40+Math.sin(x*.019)*11+p.y*105;g.fillStyle="rgba("+(p.j>.68?"220,242,255":"28,145,240")+","+(0.10+p.j*.44)+")";g.fillRect(x,y,.7+p.j*1.6,.7+p.j*1.6)}
  for(let x=190;x<w;x+=25){const y=ridgeY(x,4,now)+17;g.strokeStyle="rgba(52,136,204,.12)";g.beginPath();g.moveTo(x,y);g.lineTo(x+85,h*.58);g.stroke()}
 }
 function drawRiver(now,elapsed){
  for(let k=-9;k<=9;k++){g.beginPath();for(let x=170;x<w+60;x+=9){const y=riverY(x,now,k*7.1);x===170?g.moveTo(x,y):g.lineTo(x,y)}const edge=Math.abs(k)/9,alpha=.055+(1-edge)*.15;g.strokeStyle=k===0?"rgba(245,251,255,.96)":"rgba("+(k%3===0?"92,218,255":"22,147,255")+","+alpha+")";g.lineWidth=k===0?2.5:(k%3===0?1.2:.68);g.stroke()}
  g.save();g.globalCompositeOperation="lighter";for(const p of bits){const span=w+360,x=((p.base+elapsed*p.speed+180)%span)-180,y=riverY(x,now,p.lane*.42+Math.sin(elapsed*.8+p.phase)*9);g.fillStyle=p.tone>.72?"rgba(232,249,255,.88)":"rgba(30,154,255,.62)";g.fillRect(x,y,p.size*1.85,p.size*1.85);if(p.tone>.92){g.fillStyle="rgba(83,215,255,.17)";g.fillRect(x-2,y-2,p.size*5,p.size*5)}}g.restore()
 }
 function drawWeaveFeed(now){const x0=w*.69,y0=h*.07;g.save();g.globalCompositeOperation="lighter";for(let k=0;k<15;k++){const x=x0+(k-7)*5.2;g.beginPath();g.moveTo(x,y0);g.bezierCurveTo(x+Math.sin(now*.0003+k)*24,h*.22,x-32,h*.35,w*.72,h*.45);g.strokeStyle="rgba("+(k%3===0?"235,248,255":"29,151,255")+","+(k%3===0?.18:.13)+")";g.lineWidth=k%3===0?1.25:.72;g.stroke()}g.restore()}
 function frame(now){
  const elapsed=(now-start)/1000,bg=g.createLinearGradient(0,0,0,h);bg.addColorStop(0,"#071825");bg.addColorStop(.55,"#03101b");bg.addColorStop(1,"#020812");g.fillStyle=bg;g.fillRect(0,0,w,h);
  const glow=g.createRadialGradient(w*.72,h*.28,5,w*.72,h*.28,w*.42);glow.addColorStop(0,"rgba(30,130,218,.2)");glow.addColorStop(1,"rgba(0,0,0,0)");g.fillStyle=glow;g.fillRect(0,0,w,h);
  for(const p of dust){g.fillStyle="rgba(44,155,244,"+p.a+")";g.fillRect(p.x,p.y,p.size,p.size)}
  drawTerrain(now);drawWeaveFeed(now);drawRiver(now,elapsed);requestAnimationFrame(frame)
 }
 addEventListener("resize",resize,{passive:true});resize();if(!matchMedia("(prefers-reduced-motion: reduce)").matches)requestAnimationFrame(frame)
})();