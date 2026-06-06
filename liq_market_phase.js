(function(){
  'use strict';
  var _mpAdxCh=null,_mpAdxPlusDI=null,_mpAdxMinusDI=null,_mpAdxLine=null;
  var _mpBBWCh=null,_mpBBWSeries=null;
  var _mpActive=false;
  var _mpPollTimer=null;

  function _mpS(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}
  function _mpW(id,p){var e=document.getElementById(id);if(e){e.style.width=Math.min(100,Math.max(0,p))+'%';}}
  function _mpL(id,p){var e=document.getElementById(id);if(e){e.style.left=Math.min(95,Math.max(2,p))+'%';}}

  function _initMpCharts(){
    var co=function(h){return{layout:{background:{type:'solid',color:'#ffffff'},textColor:'#5a5a7a'},grid:{vertLines:{color:'#e2e6ef'},horzLines:{color:'#e2e6ef'}},timeScale:{borderColor:'#e2e6ef',visible:false},rightPriceScale:{borderColor:'#e2e6ef',visible:true},width:300,height:h};};
    var adxEl=document.getElementById('mpAdxChart');
    if(adxEl&&!_mpAdxCh){_mpAdxCh=LightweightCharts.createChart(adxEl,Object.assign(co(100),{width:adxEl.clientWidth||300}));
      _mpAdxLine=_mpAdxCh.addLineSeries({color:'#f59e0b',lineWidth:2,priceLineVisible:false,lastValueVisible:true,title:'ADX'});
      _mpAdxPlusDI=_mpAdxCh.addLineSeries({color:'#10b981',lineWidth:1,priceLineVisible:false,lastValueVisible:false,title:'+DI'});
      _mpAdxMinusDI=_mpAdxCh.addLineSeries({color:'#f43f5e',lineWidth:1,priceLineVisible:false,lastValueVisible:false,title:'-DI'});
    }
    var bbwEl=document.getElementById('mpBBWChart');
    if(bbwEl&&!_mpBBWCh){_mpBBWCh=LightweightCharts.createChart(bbwEl,Object.assign(co(80),{width:bbwEl.clientWidth||300}));
      _mpBBWSeries=_mpBBWCh.addLineSeries({color:'#8b5cf6',lineWidth:2,priceLineVisible:false,lastValueVisible:true});
    }
  }

  function _updateMpCharts(data){
    var ind=data.indicators||{};
    var adxH=data.adxHistory||[];
    if(_mpAdxLine&&adxH.length){
      _mpAdxLine.setData(adxH.map(function(d){return{time:d.time,value:d.adx};}));
      _mpAdxPlusDI.setData(adxH.map(function(d){return{time:d.time,value:d.plus_di};}));
      _mpAdxMinusDI.setData(adxH.map(function(d){return{time:d.time,value:d.minus_di};}));
      if(_mpAdxCh)_mpAdxCh.timeScale().fitContent();
    }
    var bbH=data.bbwHistory||[];
    if(_mpBBWSeries&&bbH.length){
      _mpBBWSeries.setData(bbH.map(function(d){return{time:d.time,value:d.bbw};}));
      if(_mpBBWCh)_mpBBWCh.timeScale().fitContent();
    }
  }

  function _renderMpPanel(data){
    if(!data||!data.marketPhase)return;
    var mp=data.marketPhase;
    var pri=mp.primary||{};
    var sec=mp.secondary;
    var ind=data.indicators||{};
    var adx=ind.adx||{};
    var atr=ind.atr||{};
    var bb=ind.bollingerBands||{};
    var vol=ind.volume||{};
    var body=ind.candleBody||{};
    var pa=ind.priceAction||{};
    var kl=data.keyLevels||{};

    // Hero
    _mpS('mpPhaseIcon',pri.icon||'?');
    _mpS('mpPhaseLabel',pri.label||'Analyzing...');
    _mpS('mpPhaseDesc',pri.description||'');
    var heroEl=document.getElementById('mpHero');
    if(heroEl)heroEl.style.borderColor=(pri.color||'#f59e0b')+'44';
    _mpS('mpConfValue',(pri.score||0)+'%');
    var confEl=document.getElementById('mpConfValue');
    if(confEl)confEl.style.color=pri.color||'#f59e0b';
    if(sec&&sec.label){
      var sw=document.getElementById('mpSecondaryWrap');
      if(sw)sw.style.display='';
      _mpS('mpSecValue',sec.label+' ('+sec.score+'%)');
    }
    _mpS('mpStrategy',pri.strategy||'');

    // Phase scores
    var allScores=mp.allScores||{};
    _mpW('mpScoreConsolidation',allScores.consolidation||0);
    _mpS('mpScoreConsolidationVal',(allScores.consolidation||0)+'%');
    _mpW('mpScoreBullish',allScores.trending_bullish||0);
    _mpS('mpScoreBullishVal',(allScores.trending_bullish||0)+'%');
    _mpW('mpScoreBearish',allScores.trending_bearish||0);
    _mpS('mpScoreBearishVal',(allScores.trending_bearish||0)+'%');
    _mpW('mpScoreVolatile',allScores.volatile||0);
    _mpS('mpScoreVolatileVal',(allScores.volatile||0)+'%');
    _mpW('mpScoreSilent',allScores.silent||0);
    _mpS('mpScoreSilentVal',(allScores.silent||0)+'%');

    // ADX
    _mpS('mpAdxVal',adx.value||'0');
    _mpS('mpPlusDI',adx.plusDI||'0');
    _mpS('mpMinusDI',adx.minusDI||'0');
    _mpS('mpDIBias',adx.bias||'neutral');
    _mpS('mpAdxTrend',adx.trend||'stable');
    var adxB=document.getElementById('mpAdxBadge');
    if(adxB){adxB.textContent=adx.value+' '+adx.trend;
      adxB.style.background=adx.value>25?'rgba(16,185,129,0.12)':adx.value<15?'rgba(244,63,94,0.12)':'rgba(245,158,11,0.1)';
      adxB.style.color=adx.value>25?'#10b981':adx.value<15?'#f43f5e':'#f59e0b';}

    // ATR
    _mpS('mpAtrVal',atr.value||'0');
    _mpS('mpAtrPct',(atr.percent||0)+'%');
    _mpS('mpAtrTrend',atr.trend||'stable');
    var atrPct=Math.min(100,(atr.percent||0)/3*100);
    _mpW('mpAtrMeter',atrPct);
    _mpL('mpAtrMeter',atrPct);
    var atrB=document.getElementById('mpAtrBadge');
    if(atrB){atrB.textContent=atr.trend||'stable';
      atrB.style.background=atr.trend==='expanding'?'rgba(244,63,94,0.12)':'rgba(16,185,129,0.1)';
      atrB.style.color=atr.trend==='expanding'?'#f43f5e':'#10b981';}

    // Bollinger Bands
    _mpS('mpBBUpper',bb.upper||'0');
    _mpS('mpBBMiddle',bb.middle||'0');
    _mpS('mpBBLower',bb.lower||'0');
    _mpS('mpBBWidth',bb.width||'0');
    _mpS('mpBBPctB',bb.percentB||'0.5');
    _mpS('mpBBPercentile',(bb.widthPercentile||50)+'th');
    var bbP=bb.percentB||0.5;
    var bbBand=document.getElementById('mpBBBand');
    if(bbBand)bbBand.style.top=(10+bbP*20)+'%';
    var bbB=document.getElementById('mpBBBadge');
    if(bbB){bbB.textContent='W: '+(bb.widthPercentile||50)+'th';
      bbB.style.background=bb.widthPercentile<30?'rgba(245,158,11,0.12)':'rgba(139,92,246,0.12)';
      bbB.style.color=bb.widthPercentile<30?'#f59e0b':'#8b5cf6';}

    // Volume
    _mpS('mpVolRatio',(vol.ratio||0)+'x');
    _mpS('mpVolCurrent',vol.current||'0');
    _mpS('mpVolAvg',vol.average||'0');
    _mpS('mpVolTrend',vol.trend||'stable');
    var volPct=Math.min(100,(vol.ratio||1)/3*100);
    _mpW('mpVolMeter',volPct);
    _mpL('mpVolMeter',volPct);
    var volB=document.getElementById('mpVolBadge');
    if(volB){volB.textContent=vol.trend||'stable';
      volB.style.background=vol.trend==='expanding'?'rgba(16,185,129,0.12)':vol.trend==='contracting'?'rgba(244,63,94,0.12)':'rgba(245,158,11,0.1)';
      volB.style.color=vol.trend==='expanding'?'#10b981':vol.trend==='contracting'?'#f43f5e':'#f59e0b';}

    // Candle Body
    _mpS('mpBodyRatio',body.recentRatio||'0');
    _mpS('mpBodyAvg',body.avgRatio||'0');
    _mpS('mpBodyAssess',body.assessment||'moderate');
    var bodyPct=(body.recentRatio||0.5)*100;
    _mpW('mpBodyMeter',bodyPct);
    _mpL('mpBodyMeter',bodyPct);
    var bB=document.getElementById('mpBodyBadge');
    if(bB){bB.textContent=body.assessment||'moderate';
      bB.style.background=body.assessment==='strong'?'rgba(16,185,129,0.12)':body.assessment==='weak'?'rgba(244,63,94,0.12)':'rgba(245,158,11,0.1)';
      bB.style.color=body.assessment==='strong'?'#10b981':body.assessment==='weak'?'#f43f5e':'#f59e0b';}

    // Price Action
    _mpS('mpPAPrice','$'+(pa.price||'0'));
    _mpS('mpPAMA20','$'+(pa.ma20||'0'));
    _mpS('mpPAMA50','$'+(pa.ma50||'0'));
    _mpS('mpPAMA200',pa.ma200?'$'+pa.ma200:'N/A');
    _mpS('mpPATrend',pa.maTrend||'mixed');
    _mpS('mpPARange',(pa.rangePercent||0)+'%');
    _mpS('mpPAPosition',((pa.positionInRange||0.5)*100).toFixed(0)+'% in range');
    var paB=document.getElementById('mpPABadge');
    if(paB){paB.textContent=pa.maTrend||'mixed';
      paB.style.background=pa.maTrend==='bullish'?'rgba(16,185,129,0.12)':pa.maTrend==='bearish'?'rgba(244,63,94,0.12)':'rgba(245,158,11,0.1)';
      paB.style.color=pa.maTrend==='bullish'?'#10b981':pa.maTrend==='bearish'?'#f43f5e':'#f59e0b';}

    // Key Levels
    var klEl=document.getElementById('mpKeyLevels');
    if(klEl){
      var html='';
      (kl.support||[]).forEach(function(s){
        html+='<div class="mp-kl-card"><span class="mp-kl-type" style="background:rgba(16,185,129,0.12);color:#10b981">SUP</span><span class="mp-kl-price">$'+s.price+'</span><span class="mp-kl-label">'+s.label+'</span></div>';
      });
      (kl.resistance||[]).forEach(function(r){
        html+='<div class="mp-kl-card"><span class="mp-kl-type" style="background:rgba(244,63,94,0.12);color:#f43f5e">RES</span><span class="mp-kl-price">$'+r.price+'</span><span class="mp-kl-label">'+r.label+'</span></div>';
      });
      if(kl.current_price)html+='<div class="mp-kl-card"><span class="mp-kl-type" style="background:rgba(34,211,238,0.12);color:#22d3ee">NOW</span><span class="mp-kl-price">$'+kl.current_price+'</span></div>';
      klEl.innerHTML=html||'<div class="mp-empty">No key levels</div>';
    }
  }

  function _startMpPoll(){
    _stopMpPoll();
    _mpPollTimer=setInterval(function(){
      if(_mpActive)_fetchMp(true);
    },30000);
  }
  function _stopMpPoll(){
    if(_mpPollTimer){clearInterval(_mpPollTimer);_mpPollTimer=null;}
  }

  function _fetchMp(silent){
    if(!_mpActive)return;
    var sym='BTCUSDT';
    var intv='15m';
    try{
      var ss=document.getElementById('symbolSelect');
      if(ss)sym=ss.value;
      var is=document.getElementById('intervalSelect');
      if(is)intv=is.value;
    }catch(e){}
    if(!silent){
      _mpS('mpPhaseLabel','Analyzing...');
      _mpS('mpPhaseDesc','Fetching market data for '+sym+' ('+intv+')...');
    }
    fetch('/api/market-phase',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({symbol:sym,interval:intv})
    }).then(function(r){return r.json();}).then(function(d){
      if(d.success){
        _renderMpPanel(d);
        _initMpCharts();
        _updateMpCharts(d);
      }else{
        _mpS('mpPhaseLabel','Error');
        _mpS('mpPhaseDesc',d.error||'Failed to analyze market phase');
      }
      var b=document.getElementById('marketPhaseBadge');
      if(b&&d.success&&d.marketPhase){
        b.textContent=d.marketPhase.primary.label||'?';
        b.style.background=(d.marketPhase.primary.color||'#f59e0b')+'22';
        b.style.color=d.marketPhase.primary.color||'#f59e0b';
      }
    }).catch(function(){
      _mpS('mpPhaseLabel','Connection Error');
      _mpS('mpPhaseDesc','Cannot reach server. Is it running?');
    });
  }

  function _hookTabSwitch(){
    var checkInterval=setInterval(function(){
      var btns=document.querySelectorAll('.tab-btn');
      if(!btns.length)return;
      clearInterval(checkInterval);
      btns.forEach(function(btn){
        btn.addEventListener('click',function(){
          var tab=btn.getAttribute('data-tab');
          if(tab==='market-phase'){
            _mpActive=true;
            var mpPanel=document.getElementById('panel-market-phase');
            if(mpPanel)mpPanel.classList.add('active');
            _fetchMp();
            _startMpPoll();
          }else if(_mpActive){
            _mpActive=false;
            _stopMpPoll();
            var mpPanel=document.getElementById('panel-market-phase');
            if(mpPanel)mpPanel.classList.remove('active');
          }
        });
      });
    },100);
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',_hookTabSwitch);
  }else{
    _hookTabSwitch();
  }
})();
