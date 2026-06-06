(function(){
  'use strict';
  var _evActive=false;
  var _evData=null;
  var _evFilter="all";
  var _evCountdownTimer=null;
  function _evS(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
  function _evFD(s){var d=new Date(s);var M=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];var W=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];return{day:d.getUTCDate(),month:M[d.getUTCMonth()],wk:W[d.getUTCDay()],time:d.getUTCHours().toString().padStart(2,"0")+":"+d.getUTCMinutes().toString().padStart(2,"0")+" UTC"};}

  function _evRender(data){
    var el=document.getElementById("evTimeline");
    if(!el)return;
    var events=data.events||[];
    if(!events.length){el.innerHTML="<div class=ev-empty>No upcoming events</div>";return;}
    var f=events;
    if(_evFilter==="macro")f=events.filter(function(e){return e.category==="macro";});
    else if(_evFilter==="crypto")f=events.filter(function(e){return e.category==="crypto";});
    else if(_evFilter==="high")f=events.filter(function(e){return e.impact==="high";});
    el.innerHTML=f.map(function(ev){
      var d=_evFD(ev.date);
      return "<div class=ev-row impact-"+ev.impact+" ev-prox-"+(ev.proximity||"upcoming")+" data-ev-id="+ev.id+">"+
        "<div class=ev-row-left><span class=ev-row-day>"+d.day+"</span><span class=ev-row-month>"+d.month+"</span></div>"+
        "<div class=ev-row-center><div class=ev-row-name>"+ev.icon+" "+ev.name+"</div>"+
        "<div class=ev-row-desc>"+(ev.whatItMeasures||"")+"</div></div>"+
        "<div class=ev-row-right><span class=ev-row-countdown>"+ev.countdown+"</span>"+
        "<span class=ev-row-badge ev-badge-"+ev.impact+">"+ev.impact+" impact</span>"+
        "<span style=font-size:9px;color:var(--text-muted);font-family:var(--font-mono)>"+d.time+"</span></div></div>";
    }).join("" );
    el.querySelectorAll(".ev-row").forEach(function(row){
      row.addEventListener("click",function(){
        var id=row.getAttribute("data-ev-id");
        var ev=events.find(function(e){return e.id===id;});
        if(ev)_evDetail(ev);
      });
    });
  }

  function _evDetail(ev){
    var o=document.getElementById("evDetailOverlay");
    if(!o)return;
    _evS("evDetailIcon",ev.icon);
    _evS("evDetailName",ev.name);
    var d=_evFD(ev.date);
    _evS("evDetailDate",d.wk+", "+d.month+" "+d.day+" 2026 — "+d.time+" | "+ev.countdown+" away");
    _evS("evDetailMeasures",ev.whatItMeasures||"No description.");
    _evS("evDetailImpact",ev.cryptoImpact||"No impact data.");
    _evS("evDetailSource","Source: "+ev.source+(ev.frequency?" | Frequency: "+ev.frequency:""));
    var sEl=document.getElementById("evDetailScenarios");
    if(sEl){var sc=ev.scenarios||{};var k=Object.keys(sc);
      sEl.innerHTML=k.map(function(key){
        var t=sc[key];var ib=t.indexOf("+")>=0;var ibe=t.indexOf("bullish")>=0;var iba=t.indexOf("bearish")>=0;
        var cls=(ib||ibe)&&!iba?"ev-scenario-bull":(iba&&!(ib||ibe))?"ev-scenario-bear":"ev-scenario-neutral";
        var lbl=(ib||ibe)&&!iba?"Bullish":(iba&&!(ib||ibe))?"Bearish":"Mixed";
        var lcls=cls;
        return "<div class=ev-scenario-row><span class=ev-scenario-label "+lcls+">"+lbl+"</span><span class=ev-scenario-text><strong>"+key.replace(/_/g," ")+"</strong>: "+t+"</span></div>";
      }).join("" );
    }
    o.style.display="flex";
  }

  function _evFetch(){
    if(!_evActive)return;
    fetch("/api/events",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})
    .then(function(r){return r.json();}).then(function(d){
      if(d.success){
        _evData=d;_evRender(d);
        _evS("evTotal",d.summary.total);
        _evS("evHighImpact",d.summary.highImpact);
        _evS("evThisWeek",d.summary.thisWeek);
        if(d.summary.nextHighImpact&&d.summary.nextHighImpact.name){
          _evS("evNextName",d.summary.nextHighImpact.name);
          _evS("evNextCountdown",d.summary.nextHighImpact.countdown+" — Next High Impact");
        }
        var b=document.getElementById("eventsBadge");
        if(b){b.textContent=d.summary.highImpact||"—";
          b.style.background=d.summary.highImpact>0?"rgba(244,63,94,0.2)":"rgba(74,84,120,0.2)";
          b.style.color=d.summary.highImpact>0?"#f43f5e":"#4a5478";}
      }
    }).catch(function(){});
  }

  function _evStartPoll(){_evStopPoll();_evCountdownTimer=setInterval(function(){if(_evActive&&_evData)_evFetch();},60000);}
  function _evStopPoll(){if(_evCountdownTimer){clearInterval(_evCountdownTimer);_evCountdownTimer=null;}}

  function _evHook(){
    var ci=setInterval(function(){
      var btns=document.querySelectorAll(".tab-btn");
      if(!btns.length)return;clearInterval(ci);
      document.querySelectorAll(".ev-filter-btn").forEach(function(b){
        b.addEventListener("click",function(){
          document.querySelectorAll(".ev-filter-btn").forEach(function(x){x.classList.remove("active");});
          b.classList.add("active");_evFilter=b.getAttribute("data-ef");if(_evData)_evRender(_evData);
        });
      });
      var cb=document.getElementById("evDetailClose");
      var ov=document.getElementById("evDetailOverlay");
      if(cb)cb.addEventListener("click",function(){ov.style.display="none";});
      if(ov)ov.addEventListener("click",function(e){if(e.target===ov)ov.style.display="none";});
      btns.forEach(function(btn){
        btn.addEventListener("click",function(){
          var tab=btn.getAttribute("data-tab");
          if(tab==="events"){
            _evActive=true;var p=document.getElementById("panel-events");if(p)p.classList.add("active");
            _evFetch();_evStartPoll();
          }else if(_evActive){
            _evActive=false;_evStopPoll();
            var p=document.getElementById("panel-events");if(p)p.classList.remove("active");
          }
        });
      });
    },100);
  }

  if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",_evHook);}else{_evHook();}
})();