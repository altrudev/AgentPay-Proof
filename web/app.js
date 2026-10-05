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
 let w=0,h=0,dpr=1,start=performance.now(),bits=[],stars=[],peaks=[];
 const rand=i=>{const n=Math.sin(i*131.73+17.91)*43758.5453123;return n-Math.floor(n)};
 function resize(){
  dpr=Math.min(devicePixelRatio||1,2);w=innerWidth;h=innerHeight;c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);c.style.width=w+"px";c.style.height=h+"px";g.setTransform(dpr,0,0,dpr,0,0);
  bits=Array.from({length:760},(_,i)=>({base:rand(i)*(w+420)-210,lane:(rand(i+700)-.5)*240,speed:28+rand(i+1200)*130,size:.35+rand(i+1800)*1.8,phase:rand(i+2400)*6.283,tone:rand(i+3100)}));
  stars=Array.from({length:1200},(_,i)=>({x:rand(i+4100)*w,y:rand(i+5200)*h*.7,a:.03+rand(i+6100)*.48,size:.3+rand(i+7000)*1.5}));
  peaks=Array.from({length:18},(_,i)=>({x:w*(.34+i/17*.66),y:h*(.26+rand(i+8100)*.16),width:55+rand(i+9000)*130,height:40+rand(i+9800)*105,seed:i}));
 }
 function riverY(x,t,lane=0){return h*.435+Math.sin(x*.006+t*.00033)*43+Math.sin(x*.014-t*.00017)*16+lane}
 function drawMountains(now){
  const left=w*.34,right=w*1.02,base=h*.455;
  const ridge=[];
  for(let i=0;i<=84;i++){
    const x=left+(right-left)*i/84;
    const n1=Math.sin(i*.63+1.2)*.5+.5,n2=Math.sin(i*.21+2.7)*.5+.5,n3=Math.sin(i*.11+.9)*.5+.5;
    const peak=Math.pow(Math.max(n1*.62+n2*.27+n3*.11,.05),1.7);
    const y=base-peak*(h*.20)-Math.sin(i*.09)*h*.025;
    ridge.push([x,y]);
  }
  const layers=[{dy:42,a:.13,stroke:.12},{dy:21,a:.16,stroke:.17},{dy:0,a:.24,stroke:.28}];
  for(const L of layers){
    g.beginPath();g.moveTo(left,h*.56);
    for(const [x,y] of ridge)g.lineTo(x,y+L.dy);
    g.lineTo(right,h*.56);g.closePath();
    const grad=g.createLinearGradient(0,h*.18,0,h*.55);grad.addColorStop(0,`rgba(20,79,129,${L.a})`);grad.addColorStop(.72,`rgba(6,32,55,${L.a*.7})`);grad.addColorStop(1,'rgba(2,11,20,.03)');g.fillStyle=grad;g.fill();
    g.strokeStyle=`rgba(113,197,250,${L.stroke})`;g.lineWidth=L.dy===0?1.15:.65;g.stroke();
  }
  g.save();g.globalCompositeOperation='lighter';
  for(let i=1;i<ridge.length-1;i++){
    const [x,y]=ridge[i];
    if(i%3===0){g.strokeStyle='rgba(39,139,214,.11)';g.lineWidth=.55;g.beginPath();g.moveTo(x,y);g.lineTo(x+36,base+65);g.stroke()}
    const count=i%4===0?5:2;
    for(let j=0;j<count;j++){
      const rx=(rand(i*91+j)-.5)*32,ry=rand(i*137+j)*(base-y)*.8;
      const bright=rand(i*211+j)>.72;
      g.fillStyle=bright?'rgba(226,246,255,.72)':'rgba(28,148,244,.46)';
      const z=bright?1.7:1.05;g.fillRect(x+rx,y+ry,z,z)
    }
  }
  g.restore();
 }
 function drawTerrainMesh(now){
  for(let row=0;row<9;row++){
   g.beginPath();
   for(let x=180;x<w+25;x+=14){const y=h*(.31+row*.029)+Math.sin(x*.0064+row*1.8+now*.000065)*18+Math.sin(x*.018-row*.7)*6;x===180?g.moveTo(x,y):g.lineTo(x,y)}
   g.strokeStyle=`rgba(46,127,192,${.04+row*.012})`;g.lineWidth=.6;g.stroke()
  }
  for(let x=200;x<w;x+=34){g.strokeStyle='rgba(49,128,190,.055)';g.beginPath();g.moveTo(x,h*.3);g.lineTo(x+110,h*.58);g.stroke()}
 }
 function drawWeaveFlow(now){
  const x0=w*.71,top=h*.055,join=h*.38;
  g.save();g.globalCompositeOperation='lighter';
  for(let k=-9;k<=9;k++){
   const x=x0+k*5.2;
   g.beginPath();g.moveTo(x,top);
   g.bezierCurveTo(x+Math.sin(now*.00025+k)*26,h*.18,x-35,h*.29,w*.715,join);
   g.bezierCurveTo(w*.69,h*.41,w*.74,h*.43,w*.79,h*.455);
   g.strokeStyle=k%3===0?'rgba(240,249,255,.23)':'rgba(22,149,255,.17)';g.lineWidth=k%3===0?1.25:.72;g.stroke()
  }
  g.restore()
 }
 function drawRiver(now,elapsed){
  for(let k=-11;k<=11;k++){
   g.beginPath();for(let x=170;x<w+80;x+=8){const y=riverY(x,now,k*6.4);x===170?g.moveTo(x,y):g.lineTo(x,y)}
   const edge=Math.abs(k)/11,a=.04+(1-edge)*.16;g.strokeStyle=k===0?'rgba(246,252,255,.97)':`rgba(${k%4===0?'96,220,255':'24,148,255'},${a})`;g.lineWidth=k===0?2.7:(k%4===0?1.2:.6);g.stroke()
  }
  g.save();g.globalCompositeOperation='lighter';
  for(const p of bits){const span=w+420,x=((p.base+elapsed*p.speed+210)%span)-210,y=riverY(x,now,p.lane*.4+Math.sin(elapsed*.75+p.phase)*10);g.fillStyle=p.tone>.76?'rgba(232,249,255,.9)':'rgba(30,154,255,.64)';g.fillRect(x,y,p.size*1.9,p.size*1.9);if(p.tone>.93){g.fillStyle='rgba(91,222,255,.18)';g.fillRect(x-2,y-2,p.size*5,p.size*5)}}
  g.restore()
 }
 function frame(now){
  const elapsed=(now-start)/1000,bg=g.createLinearGradient(0,0,0,h);bg.addColorStop(0,'#071827');bg.addColorStop(.48,'#04111d');bg.addColorStop(1,'#020812');g.fillStyle=bg;g.fillRect(0,0,w,h);
  const halo=g.createRadialGradient(w*.73,h*.27,10,w*.73,h*.27,w*.43);halo.addColorStop(0,'rgba(37,142,226,.22)');halo.addColorStop(.5,'rgba(14,76,133,.08)');halo.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=halo;g.fillRect(0,0,w,h);
  for(const p of stars){g.fillStyle=`rgba(43,154,246,${p.a})`;g.fillRect(p.x,p.y,p.size,p.size)}
  drawMountains(now);drawTerrainMesh(now);drawWeaveFlow(now);drawRiver(now,elapsed);
  requestAnimationFrame(frame)
 }
 addEventListener('resize',resize,{passive:true});resize();if(!matchMedia('(prefers-reduced-motion: reduce)').matches)requestAnimationFrame(frame)
})();
