const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=20)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};
let liveConfig={enabled:false};
let connectedAccount=null;
let currentProof=null;

function fitStage(){
 const stage=$("#stage");
 const mobile=matchMedia("(max-width:900px)").matches;
 if(mobile){
  const scale=innerWidth/1672;
  stage.style.transform="scale("+scale+")";
  document.body.style.height=(940*scale)+"px";
  return;
 }
 const scale=Math.min(innerWidth/1672,innerHeight/940);
 stage.style.transform="translate(-50%,-50%) scale("+scale+")";
 document.body.style.height="";
}
addEventListener("resize",fitStage,{passive:true});
fitStage();

function showStatus(title,message,actions=[]){
 $("#status-title").textContent=title;
 $("#status-message").textContent=message;
 const box=$("#status-actions");box.innerHTML="";
 for(const action of actions){
  const b=document.createElement("button");b.type="button";b.textContent=action.label;
  b.onclick=()=>{action.onClick?.();$("#status-dialog").close()};
  box.appendChild(b);
 }
 $("#status-dialog").showModal();
}

function drawStages(upto=-1,denied=-1){
 const host=$("#stage-state");host.innerHTML="";
 for(let i=0;i<=upto;i++){
  const span=document.createElement("span");
  if(i===denied)span.className="denied";
  host.appendChild(span);
 }
}

async function postJson(path,payload){
 const r=await fetch(path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(payload)});
 const d=await r.json();
 if(!r.ok){const e=new Error(d.error||"request failed");e.status=r.status;e.payload=d;throw e}
 return d;
}

function addActivity(name,status,amount="—",kind="info"){
 const list=$("#activity-list"),row=document.createElement("p");
 row.innerHTML='<i class="'+kind+'"></i><b>'+esc(name)+'</b><em>'+esc(status)+'</em><span>'+esc(amount)+'</span><small>now</small>';
 list.prepend(row);
 while(list.children.length>5)list.lastElementChild.remove();
}

async function connectWallet(){
 if(!window.ethereum){
  showStatus("Wallet not detected","Enable MetaMask, Coinbase Wallet, or another Base-compatible EVM wallet in this browser, then try again.");
  return null;
 }
 try{
  const accounts=await ethereum.request({method:"eth_requestAccounts"});
  connectedAccount=accounts?.[0]||null;
  $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
  $("#runtime-state").textContent=connectedAccount?"Wallet ready":"Online";
  return connectedAccount;
 }catch(e){
  showStatus("Wallet connection stopped",e?.code===4001?"You rejected the wallet connection request.":(e?.message||"Wallet connection failed."));
  return null;
 }
}

async function ensureBase(chainId){
 try{
  await ethereum.request({method:"wallet_switchEthereumChain",params:[{chainId}]});
 }catch(e){
  if(e?.code!==4902)throw e;
  await ethereum.request({method:"wallet_addEthereumChain",params:[{
   chainId,chainName:"Base",nativeCurrency:{name:"Ether",symbol:"ETH",decimals:18},
   rpcUrls:["https://mainnet.base.org"],blockExplorerUrls:["https://basescan.org"]
  }]});
 }
}

async function reconcile(decisionId,txHash,sender){
 for(let attempt=0;attempt<30;attempt++){
  try{return await postJson("/api/live/reconcile",{decision_id:decisionId,transaction_hash:txHash,sender})}
  catch(e){
   if(e.status===409&&e.payload?.error==="settlement-not-observed"){
    $("#runtime-state").textContent="Reconciling";
    await new Promise(r=>setTimeout(r,2000));
    continue;
   }
   throw e;
  }
 }
 throw new Error("settlement-reconciliation-timeout");
}

async function runLive(service="code"){
 if(!liveConfig.enabled){showStatus("Live mode unavailable","Live Base settlement is not configured.");return}
 const sender=connectedAccount||await connectWallet();
 if(!sender)return;

 const document={
  code:"Review this bounded code-analysis request and return a deterministic verified report.",
  research:"Summarize this bounded public-data research request with verifiable evidence.",
  "3d":"Create the bounded 3D-generation service result represented by the AgentPay demo."
 }[service]||"Run the governed AgentPay service.";

 let prepared;
 try{
  drawStages(1);
  addActivity("Quote","Prepared","—","info");
  prepared=await postJson("/api/live/prepare",{amount_atomic:250000,document});
  if(prepared.status==="DENIED"){
   currentProof=prepared.proof;drawStages(2,2);addActivity("Authority","Denied","—","bad");return;
  }
  drawStages(2);
  await ensureBase(prepared.wallet_request.chainId);
  $("#runtime-state").textContent="Wallet approval";
  let txHash;
  try{
   txHash=await ethereum.request({method:"eth_sendTransaction",params:[{
    from:sender,to:prepared.wallet_request.to,value:prepared.wallet_request.value,data:prepared.wallet_request.data
   }]});
  }catch(e){
   if(e?.code===4001){
    await postJson("/api/live/abort",{decision_id:prepared.decision_id}).catch(()=>{});
    addActivity("Settlement","Wallet rejected","—","bad");
   }else{
    await postJson("/api/live/uncertain",{decision_id:prepared.decision_id}).catch(()=>{});
    addActivity("Settlement","In doubt","—","info");
   }
   throw e;
  }
  drawStages(3);
  addActivity("Settlement","Broadcast","0.25 USDC","info");
  const result=await reconcile(prepared.decision_id,txHash,sender);
  currentProof=result.proof;
  for(let i=4;i<7;i++){drawStages(i);await new Promise(r=>setTimeout(r,120))}
  addActivity("AgentPay","Verified","0.25 USDC","info");
  $("#runtime-state").textContent="Verified";
 }catch(e){
  console.error(e);
  $("#runtime-state").textContent="Attention";
  showStatus("Live payment stopped",e?.code===4001?"You rejected the wallet request. No payment was sent.":(e?.message||"Live payment failed."));
 }
}

function openProof(){
 if(!currentProof){showStatus("No proof yet","Run a service first. A verified proof will appear here.");return}
 const p=currentProof;
 const rows=[["Intent",p.intent?.intent_id],["Quote",p.quote?.quote_id],["Authority",p.authority?.decision],["Settlement",p.settlement?.transaction_hash],["Execution",p.result?.result_digest],["Observation",p.observation?.observer_id],["Proof",p.proof_hash]];
 $("#evidence-grid").innerHTML=rows.filter(x=>x[1]).map(x=>'<article><small>'+esc(x[0])+'</small><div>'+esc(short(x[1],24))+'</div></article>').join("");
 $("#evidence-json").textContent=JSON.stringify(p,null,2);
 $("#evidence-dialog").showModal();
}

async function refreshNetwork(){
 try{
  const r=await fetch("/api/live/network"),d=await r.json();
  if(!r.ok||!d.online)throw new Error();
  $("#network-block").textContent=String(d.block);
  $("#network-gas").textContent=String(d.gas_gwei)+" gwei";
  $("#network-rpc").textContent=String(d.rpc_ms)+" ms";
  if(!connectedAccount)$("#runtime-state").textContent="Online";
 }catch{
  $("#runtime-state").textContent="RPC offline";
 }
}

async function init(){
 try{
  const r=await fetch("/api/live/config"),d=await r.json();liveConfig=d;
  const label=d.enabled?"Base Mainnet":"Demo";
  $("#network-label").textContent=label;$("#runtime-network").textContent=label;
  if(d.enabled)refreshNetwork();
  if(window.ethereum){
   const accounts=await ethereum.request({method:"eth_accounts"}).catch(()=>[]);
   connectedAccount=accounts?.[0]||null;
   $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
   ethereum.on?.("accountsChanged",accounts=>{
    connectedAccount=accounts?.[0]||null;
    $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
   });
  }
 }catch{ $("#runtime-state").textContent="Unavailable"; }
}
$("#run-service").onclick=()=>runLive("code");
$("#nav-run").onclick=()=>runLive("code");
$("#network-control").onclick=()=>connectWallet();
$("#nav-proofs").onclick=()=>openProof();
$("#explore").onclick=()=>document.querySelector(".svc-code").focus();
$("#search-control").onclick=()=>showStatus("Search","Search is outside the competition vertical slice.");
$("#theme-control").onclick=()=>document.body.classList.toggle("dim");
$("#menu-control").onclick=()=>showStatus("AgentPay Proof","Run a Service starts the governed Base payment flow.");
document.querySelectorAll(".svc").forEach(b=>b.onclick=()=>runLive(b.dataset.service));
init();
setInterval(refreshNetwork,30000);