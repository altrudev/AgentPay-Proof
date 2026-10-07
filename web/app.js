let currentProof=null;
let liveConfig={enabled:false};
let connectedAccount=null;
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
const short=(v,n=20)=>{v=String(v??"");return v.length>n?v.slice(0,n)+"…":v};

function fitStage(){
  const stage=$("#stage");
  const scale=Math.min(innerWidth/1672,innerHeight/940);
  stage.style.transform="translate(-50%,-50%) scale("+scale+")";
}
addEventListener("resize",fitStage,{passive:true});
fitStage();

function showStatus(title,message){
  $("#status-title").textContent=title;
  $("#status-message").textContent=message;
  $("#status-dialog").showModal();
}

function resetStages(){
  document.querySelectorAll(".step").forEach(s=>s.classList.remove("pass","denied"));
}
function markStages(upto,denied=-1){
  document.querySelectorAll(".step").forEach((s,i)=>{
    s.classList.toggle("pass",i<=upto&&i!==denied);
    s.classList.toggle("denied",i===denied);
  });
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
  row.className="";
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
      chainId,chainName:"Base",
      nativeCurrency:{name:"Ether",symbol:"ETH",decimals:18},
      rpcUrls:["https://mainnet.base.org"],
      blockExplorerUrls:["https://basescan.org"]
    }]});
  }
}

async function reconcile(decisionId,txHash,sender){
  for(let attempt=0;attempt<30;attempt++){
    try{
      return await postJson("/api/live/reconcile",{decision_id:decisionId,transaction_hash:txHash,sender});
    }catch(e){
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
  if(!liveConfig.enabled){showStatus("Live mode unavailable","Live Base settlement is not configured on this server.");return}
  const sender=connectedAccount||await connectWallet();
  if(!sender)return;

  const document={
    code:"Run the bounded AgentPay code analysis service and return independently verifiable evidence.",
    research:"Run the bounded AgentPay public data research service and return independently verifiable evidence.",
    "3d":"Run the bounded AgentPay 3D generation service and return independently verifiable evidence."
  }[service]||"Run the bounded AgentPay service and return independently verifiable evidence.";

  resetStages();
  try{
    markStages(1);
    addActivity("Quote","Prepared","—","info");

    const prepared=await postJson("/api/live/prepare",{amount_atomic:250000,document});
    if(prepared.status==="DENIED"){
      currentProof=prepared.proof;markStages(2,2);addActivity("Authority","Denied","—","bad");return;
    }

    markStages(2);
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

    markStages(3);
    addActivity("Settlement","Broadcast","0.25 USDC","info");
    $("#runtime-state").textContent="Observing chain";

    const result=await reconcile(prepared.decision_id,txHash,sender);
    currentProof=result.proof;
    for(let i=4;i<7;i++){markStages(i);await new Promise(r=>setTimeout(r,120))}
    addActivity("AgentPay","Verified","0.25 USDC","ok");
    $("#runtime-state").textContent="Verified";
  }catch(e){
    console.error(e);
    if($("#runtime-state").textContent!=="Verified")$("#runtime-state").textContent="Attention";
    showStatus("Live payment stopped",e?.code===4001?"You rejected the wallet request. No payment was sent.":(e?.message||"Live payment failed."));
  }
}

function openProof(){
  if(!currentProof){showStatus("No proof yet","Run a service first. A verified proof will appear here.");return}
  const p=currentProof;
  const rows=[
    ["Intent",p.intent?.intent_id],["Quote",p.quote?.quote_id],["Authority",p.authority?.decision],
    ["Settlement",p.settlement?.transaction_hash],["Execution",p.result?.result_digest],
    ["Observation",p.observation?.observer_id],["Proof",p.proof_hash]
  ];
  $("#evidence-grid").innerHTML=rows.filter(x=>x[1]).map(x=>'<article><small>'+esc(x[0])+'</small><div>'+esc(short(x[1],24))+'</div></article>').join("");
  $("#evidence-json").textContent=JSON.stringify(p,null,2);
  $("#evidence-dialog").showModal();
}

async function refreshNetwork(){
  try{
    const r=await fetch("/api/live/network"),d=await r.json();
    if(!r.ok||!d.online)throw new Error(d.error||"rpc-unavailable");
    $("#network-block").textContent=String(d.block);
    $("#network-gas").textContent=String(d.gas_gwei)+" gwei";
    $("#network-rpc").textContent=String(d.rpc_ms)+" ms";
    if(!connectedAccount)$("#runtime-state").textContent="Online";
  }catch{
    $("#network-block").textContent="—";
    $("#network-gas").textContent="—";
    $("#network-rpc").textContent="—";
    if(!connectedAccount)$("#runtime-state").textContent="RPC offline";
  }
}

async function init(){
  try{
    const r=await fetch("/api/live/config"),d=await r.json();
    liveConfig=d;
    const label=d.enabled?"Base Mainnet":"Demo / Base";
    $("#network-label").textContent=label;
    $("#runtime-network").textContent=d.enabled?"Base Mainnet":"Demo";
    if(d.enabled)refreshNetwork();

    if(window.ethereum){
      const accounts=await ethereum.request({method:"eth_accounts"}).catch(()=>[]);
      connectedAccount=accounts?.[0]||null;
      $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
      ethereum.on?.("accountsChanged",accounts=>{
        connectedAccount=accounts?.[0]||null;
        $("#wallet-state").textContent=connectedAccount?short(connectedAccount,12):"Not connected";
        $("#runtime-state").textContent=connectedAccount?"Wallet ready":"Online";
      });
    }
  }catch{
    $("#runtime-state").textContent="Unavailable";
  }
}

$("#run-service").onclick=()=>runLive("code");
$("#nav-run").onclick=()=>runLive("code");
$("#network-control").onclick=()=>connectWallet();
$("#nav-proofs").onclick=()=>openProof();
$("#explore").onclick=()=>document.querySelector(".svc").focus();
document.querySelectorAll(".svc").forEach(b=>b.onclick=()=>runLive(b.dataset.service));
$("#search-control").onclick=()=>showStatus("Search","Service search is outside this competition vertical slice.");
$("#theme-control").onclick=()=>document.body.classList.toggle("dim");
$("#menu-control").onclick=()=>showStatus("AgentPay Proof","Run a Service starts the governed Base payment flow.");

init();
setInterval(refreshNetwork,30000);
