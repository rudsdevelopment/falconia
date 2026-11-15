/* Falconia analysis core v1.0 — independent prototype, not an operational alert service. */
(function (root) {
'use strict';
const VERSION='falconia-2.0.0', R=6371.007180918, K=Math.cos(Math.PI/6), DAY=86400000;
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const median=a=>{a=[...a].sort((x,y)=>x-y);return a.length?(a[Math.floor((a.length-1)/2)]+a[Math.ceil((a.length-1)/2)])/2:null;};
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
function csv(text){
 text=String(text).replace(/^\uFEFF/,'');const first=text.split(/\r?\n/)[0];const sep=(first.match(/;/g)||[]).length>(first.match(/,/g)||[]).length?';':',';
 const rows=[];let row=[],field='',quoted=false;
 for(let i=0;i<text.length;i++){let c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}else if(c===sep&&!quoted){row.push(field);field='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(field);if(row.some(x=>x.trim()))rows.push(row);row=[];field='';}else field+=c;}
 if(quoted)throw Error('Unclosed CSV quote');row.push(field);if(row.some(x=>x.trim()))rows.push(row);
 if(rows.length<2)throw Error('CSV needs a header and at least one record');
 const header=rows.shift().map(x=>x.trim().toLowerCase());if(new Set(header).size!==header.length)throw Error('Duplicate CSV column');
 return rows.map((r,i)=>{if(r.length!==header.length)throw Error('CSV column mismatch, row '+(i+2));return Object.fromEntries(header.map((k,j)=>[k,r[j].trim()]));});
}
function isoDate(date){if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(Date.parse(date+'T00:00:00Z'))||new Date(date+'T00:00:00Z').toISOString().slice(0,10)!==date)throw Error('Invalid date');return date;}
function number(v,name,lo,hi,optional=false){if(v===undefined||v===null||v===''){if(optional)return null;throw Error('Missing '+name);}const n=Number(v);if(!Number.isFinite(n)||n<lo||n>hi)throw Error('Invalid '+name);return n;}
function normalize(row,source,index){
 const lat=number(row.latitude??row.lat,'latitude',-90,90),lon=number(row.longitude??row.lon??row.lng,'longitude',-180,180);
 let incomingFlags=row.quality_flags;if(typeof incomingFlags==='string'){try{incomingFlags=JSON.parse(incomingFlags);}catch{incomingFlags=[];}}
 const flags=[...(Array.isArray(incomingFlags)?incomingFlags.filter(x=>typeof x==='string'):[])];
 let sensor=String(row.sensor??row.instrument??'').toUpperCase(),sat=String(row.satellite??row.platform??'').toUpperCase();
 if(['SNPP','S-NPP','N20','N21','NOAA-20','NOAA-21'].includes(sensor)){const expected={SNPP:['SNPP','S-NPP','N'], 'S-NPP':['SNPP','S-NPP','N'],N20:['N20','NOAA-20'],N21:['N21','NOAA-21'],'NOAA-20':['N20','NOAA-20'],'NOAA-21':['N21','NOAA-21']}[sensor];if(!expected.includes(sat))throw Error('Instrument alias / platform mismatch');sensor='VIIRS';flags.push('instrument_platform_alias');}
 if(!sensor){if(['A','T','AQUA','TERRA'].includes(sat))sensor='MODIS';else if(['N','N20','N21','SNPP','S-NPP','NOAA-20','NOAA-21'].includes(sat))sensor='VIIRS';else if(row.bright_ti4!==undefined)sensor='VIIRS';else if(row.brightness!==undefined)sensor='MODIS';}
 if(!['MODIS','VIIRS'].includes(sensor))throw Error('Sensor must be MODIS or VIIRS');
 const aliases={A:'Aqua',T:'Terra',AQUA:'Aqua',TERRA:'Terra',N:'S-NPP',SNPP:'S-NPP','S-NPP':'S-NPP',N20:'NOAA-20',N21:'NOAA-21','NOAA-20':'NOAA-20','NOAA-21':'NOAA-21'};
 sat=aliases[sat]||sat;if(!sat)throw Error('Missing platform');
 if((sensor==='MODIS'&&!['Aqua','Terra'].includes(sat))||(sensor==='VIIRS'&&!['S-NPP','NOAA-20','NOAA-21'].includes(sat)))throw Error('Sensor / platform mismatch');
 let timestamp;
 if(row.observed_at||row.acquired_at){const raw=String(row.observed_at??row.acquired_at);if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z$/.test(raw))throw Error('Timestamp must explicitly use UTC Z');isoDate(raw.slice(0,10));timestamp=new Date(raw).toISOString();}
 else{const d=isoDate(String(row.acq_date??row.date??''));const t=String(row.acq_time??'').padStart(4,'0');if(!/^\d{4}$/.test(t)||+t.slice(0,2)>23||+t.slice(2)>59||row.acq_time===undefined||row.acq_time==='')throw Error('Invalid UTC acquisition time');timestamp=d+'T'+t.slice(0,2)+':'+t.slice(2)+':00.000Z';}
 let confidence=row.confidence??null;const rawConfidence=confidence;
 if(sensor==='MODIS'){try{confidence=number(confidence,'MODIS confidence',0,100,true);}catch{confidence=null;flags.push(/\n|\\n|\.\.\.|dtype|Series/.test(String(rawConfidence))?'confidence_series_text':'confidence_invalid');}}
 else{const c=String(confidence??'').trim().toLowerCase();confidence={l:'low',n:'nominal',h:'high',low:'low',nominal:'nominal',high:'high',unknown:'unknown','':'unknown'}[c];if(!confidence){confidence='unknown';flags.push(/\n|\\n|\.\.\.|dtype|Series/.test(String(rawConfidence))?'confidence_series_text':'confidence_invalid');}}
 if(confidence===null||confidence==='unknown')flags.push('confidence_unknown');
 const frp=number(row.frp??row.frp_mw,'FRP',0,1e7,true),bright=number(row.brightness??row.bright_ti4??row.brightness_k,'brightness',0,2000,true);
 const rec={id:String(row.observation_id??row.id??(source+':'+(index+1))).slice(0,250),sensor,platform:sat,latitude:lat,longitude:lon,observed_at:timestamp,date:timestamp.slice(0,10),frp_mw:frp,confidence,brightness_k:bright,scan_km:number(row.scan??row.scan_km,'scan',0,100,true),track_km:number(row.track??row.track_km,'track',0,100,true),daynight:String(row.daynight??'').toUpperCase(),version:String(row.version??row.product_version??'unknown'),source:String(row.source??source).slice(0,500)};
 const rawType=row.type_code??row.type;rec.type_code=rawType===undefined||rawType===null||rawType===''?null:Number(rawType);if(rec.type_code!==null&&![0,1,2,3].includes(rec.type_code)){flags.push('type_invalid');rec.type_code=null;}
 rec.brightness_band=sensor==='MODIS'?'MODIS 21/22':(row.bright_ti4!==undefined?'VIIRS I4':'VIIRS brightness alias; verify source schema');
 if(sensor==='VIIRS'&&row.bright_ti4===undefined&&row.brightness!==undefined)flags.push('brightness_alias_verify');
 rec.quality_flags=[...new Set(flags)];
 rec.raw=row.raw&&typeof row.raw==='object'?row.raw:Object.fromEntries(Object.entries(row).filter(([k])=>!['id','source','observation_id','raw','lineage'].includes(k)));
 rec.lineage=Array.isArray(row.lineage)?row.lineage.map(x=>({...x})):[{source:rec.source,source_row:index+2}];
 if(!['D','N',''].includes(rec.daynight))throw Error('Day/night must be D or N');
 return rec;
}
function ingest(rows,source='import'){
 if(!Array.isArray(rows)||rows.length>100000)throw Error('Expected an array of at most 100,000 observations');
 const observations=[],errors=[],seen=new Map(),ids=new Set();let duplicates=0;
 rows.forEach((r,i)=>{try{const p=normalize(r,source,i);const key=JSON.stringify(Object.fromEntries(Object.entries(p).filter(([k])=>!['id','source','lineage'].includes(k))));if(seen.has(key)){duplicates++;seen.get(key).lineage.push(...p.lineage);return;}if(ids.has(p.id))throw Error('Conflicting observation ID');seen.set(key,p);ids.add(p.id);observations.push(p);}catch(e){errors.push({row:i+2,error:e.message});}});
 return {observations,errors,duplicates};
}
function inside(p,b){return p.longitude>=b[0]&&p.longitude<=b[2]&&p.latitude>=b[1]&&p.latitude<=b[3];}
function project(lon,lat){return [R*K*lon*Math.PI/180,R*Math.sin(lat*Math.PI/180)/K];}
function cell(p,km){const [x,y]=project(p.longitude,p.latitude);return Math.floor(x/km)+':'+Math.floor(y/km);}
function center(key,km){const [x,y]=key.split(':').map(Number);return {longitude:(x+.5)*km/(R*K)*180/Math.PI,latitude:Math.asin(clamp((y+.5)*km*K/R,-1,1))*180/Math.PI};}
function keep(p,q){if(!inside(p,q.bbox)||p.date<q.start||p.date>q.end)return false;if(q.sensor&&q.sensor!=='ALL'&&p.sensor!==q.sensor)return false;if(q.platform&&q.platform!=='ALL'&&p.platform!==q.platform)return false;if(q.daynight&&q.daynight!=='ALL'&&p.daynight!==q.daynight)return false;if(q.quality==='standard'){if(p.sensor==='MODIS'&&(p.confidence===null||p.confidence<30))return false;if(p.sensor==='VIIRS'&&!['nominal','high'].includes(p.confidence))return false;}if(q.quality==='high'){if(p.sensor==='MODIS'&&(p.confidence===null||p.confidence<80))return false;if(p.sensor==='VIIRS'&&p.confidence!=='high')return false;}return true;}
function dates(a,b){isoDate(a);isoDate(b);const n=Math.floor((Date.parse(b)-Date.parse(a))/DAY)+1;if(n<1||n>10000)throw Error('Select a range of 1–10,000 days');return Array.from({length:n},(_,i)=>new Date(Date.parse(a)+i*DAY).toISOString().slice(0,10));}
function analyze(observations,q){
 const rows=observations.filter(p=>keep(p,q)),daily=new Map(),cells=new Map();
 rows.forEach(p=>{const key=cell(p,q.grid);if(!daily.has(p.date))daily.set(p.date,{date:p.date,MODIS:0,VIIRS:0,m:new Set(),v:new Set(),all:new Set()});const d=daily.get(p.date);d[p.sensor]++;d[p.sensor==='MODIS'?'m':'v'].add(key);d.all.add(key);const ck=p.date+'|'+key;if(!cells.has(ck))cells.set(ck,{key,date:p.date,...center(key,q.grid),records:[],sensors:new Set()});const c=cells.get(ck);c.records.push(p);c.sensors.add(p.sensor);});
 const series=dates(q.start,q.end).map(date=>{const d=daily.get(date);return {date,MODIS:d?.MODIS||0,VIIRS:d?.VIIRS||0,modis_cells:d?.m.size||0,viirs_cells:d?.v.size||0,union_cells:d?.all.size||0,both_cells:d?[...d.m].filter(k=>d.v.has(k)).length:0,coverage:'unknown'};});
 const totals={MODIS:rows.filter(p=>p.sensor==='MODIS').length,VIIRS:rows.filter(p=>p.sensor==='VIIRS').length,cellDays:cells.size,both:series.reduce((s,d)=>s+d.both_cells,0),activeDays:daily.size};
 return {rows,series,cells:[...cells.values()],totals};
}
function distance(a,b){const rad=x=>x*Math.PI/180;const h=Math.sin(rad(b.latitude-a.latitude)/2)**2+Math.cos(rad(a.latitude))*Math.cos(rad(b.latitude))*Math.sin(rad(b.longitude-a.longitude)/2)**2;return 2*R*Math.asin(Math.sqrt(clamp(h,0,1)));}
function neighbors(p,rows){return rows.filter(x=>x.sensor!==p.sensor&&Math.abs(Date.parse(x.observed_at)-Date.parse(p.observed_at))<=90*60000&&distance(p,x)<=1).map(x=>({...x,distance_km:distance(p,x)}));}
function recurrence(cellRecords){const days=[...new Set(cellRecords.map(p=>p.date))];return {days:days.length,classification:days.length>=3?'repeated-observation':'unclassified'};}
function validateMetrics(bundle){
 const m=bundle.metric_context;if(!m||m.target!=='occupied_cell_fraction'||m.coverage_method!=='common_valid_observation_mask')throw Error('Common valid observation mask and occupied_cell_fraction metadata required');
 if(!Array.isArray(m.bbox)||m.bbox.length!==4||!m.bbox.every(Number.isFinite)||m.bbox[0]>=m.bbox[2]||m.bbox[1]>=m.bbox[3]||m.bbox[0]<-180||m.bbox[2]>180||m.bbox[1]<-90||m.bbox[3]>90)throw Error('Invalid metric bounds');
 if(m.grid_definition!=='sphere-cea-30-v1'||![1,2,5].includes(m.grid_km))throw Error('Unsupported grid definition');
 if(!m.platforms||!Array.isArray(m.platforms.MODIS)||!Array.isArray(m.platforms.VIIRS)||!m.platforms.MODIS.length||!m.platforms.VIIRS.length||m.platforms.MODIS.some(p=>!['Aqua','Terra'].includes(p))||m.platforms.VIIRS.some(p=>!['S-NPP','NOAA-20','NOAA-21'].includes(p)))throw Error('Metrics require known platform lists');
 if(typeof m.source_manifest!=='string'||!m.source_manifest.trim()||/YOUR_|PLACEHOLDER/i.test(m.source_manifest))throw Error('Metrics require a real source manifest reference');
 try{const u=new URL(m.processing_code_url);if(!['https:','http:'].includes(u.protocol)||/YOUR_|PLACEHOLDER/i.test(u.href))throw Error();}catch{throw Error('Metrics require a public HTTP(S) processing code URL');}
 const signature=[...m.platforms.MODIS].sort().join('+')+'__'+[...m.platforms.VIIRS].sort().join('+');if(m.platform_signature!==signature)throw Error('Platform signature must match canonical platform lists: '+signature);
 if(!['all','standard','high'].includes(m.quality_filter??'all'))throw Error('Unknown metric quality filter');
 if(!Array.isArray(bundle.daily_metrics)||bundle.daily_metrics.length>10000)throw Error('Invalid daily_metrics');const seen=new Set();
 const result=bundle.daily_metrics.map(d=>{isoDate(d.date);if(seen.has(d.date))throw Error('Duplicate metric day');seen.add(d.date);const n=number(d.common_valid_cells,'common valid cells',1,1e9),a=number(d.modis_occupied_cells,'MODIS occupied cells',0,n),b=number(d.viirs_occupied_cells,'VIIRS occupied cells',0,n);if(![n,a,b].every(Number.isInteger))throw Error('Cell counts must be integers');if(d.platform_signature!==m.platform_signature||!m.platform_signature)throw Error('Platform signature mismatch');return {...d,x:a/n,y:b/n,n};});return result.sort((a,b)=>a.date.localeCompare(b.date));
}
function calibrate(bundle){
 let data;try{data=validateMetrics(bundle);}catch(e){return {status:'blocked',reason:e.message};}
 if(data.length<80)return {status:'blocked',reason:'At least 80 paired valid days are required; 60 train + 20 test minimum.'};
 const cut=Math.max(60,Math.floor(data.length*.75)),train=data.slice(0,cut),test=data.slice(cut);if(test.length<20||train.filter(d=>d.x>0||d.y>0).length<30)return {status:'blocked',reason:'Need at least 30 active training days and 20 independent test days.'};
 const mx=mean(train.map(d=>d.x)),my=mean(train.map(d=>d.y)),den=train.reduce((s,d)=>s+(d.x-mx)**2,0);if(den<1e-12)return {status:'blocked',reason:'Training values have insufficient variation.'};
 const slope=Math.max(0,train.reduce((s,d)=>s+(d.x-mx)*(d.y-my),0)/den),intercept=my-slope*mx,predict=x=>clamp(intercept+slope*x,0,1);
 const raw=mean(test.map(d=>Math.abs(d.x-d.y))),adjusted=mean(test.map(d=>Math.abs(predict(d.x)-d.y))),bias=mean(test.map(d=>predict(d.x)-d.y));
 const gains=test.map(d=>Math.abs(d.x-d.y)-Math.abs(predict(d.x)-d.y));let seed=773;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};const boots=[];
 // Moving-block bootstrap on test sequence, seven observations per block; gaps remain documented.
 for(let b=0;b<300;b++){const draw=[];while(draw.length<gains.length){const start=Math.floor(random()*gains.length);for(let j=0;j<7&&draw.length<gains.length;j++)draw.push(gains[(start+j)%gains.length]);}boots.push(mean(draw));}boots.sort((a,b)=>a-b);
 const ci=[boots[7],boots[292]],accepted=adjusted<raw&&ci[0]>0;
 return {status:accepted?'provisional':'rejected',reason:accepted?'Improves agreement with VIIRS on held-out days. External validation and seasonal stability remain required.':'Held-out improvement is not supported by the bootstrap interval.',reference:'VIIRS',method:'OLS occupied-cell fraction; chronological 75/25; 7-observation block bootstrap (300)',slope,intercept,train_days:train.length,test_days:test.length,train_start:train[0].date,train_end:train.at(-1).date,test_start:test[0].date,test_end:test.at(-1).date,raw_mae:raw,adjusted_mae:adjusted,bias,gain_ci95:ci,x_min:Math.min(...train.map(d=>d.x)),x_max:Math.max(...train.map(d=>d.x)),series:data.map(d=>({date:d.date,modis_rate:d.x,viirs_rate:d.y,adjusted_modis_rate:predict(d.x),split:d.date<=train.at(-1).date?'train':'test'})),context:bundle.metric_context};
}
function seasonal(bundle,selectedDate){
 let data;try{data=validateMetrics(bundle);}catch(e){return {status:'blocked',reason:'Coverage-qualified archive required.'};}
 const target=data.find(d=>d.date===selectedDate);if(!target)return {status:'blocked',reason:'No coverage-qualified observation for this day.'};const year=+selectedDate.slice(0,4),md=selectedDate.slice(5),eligible=[];
 for(let yr=year-1;yr>=year-10;yr--){let monthday=md;if(md==='02-29'&&new Date(Date.UTC(yr,2,0)).getUTCDate()!==29)monthday='02-28';const anchor=Date.parse(yr+'-'+monthday+'T00:00:00Z');if(!Number.isFinite(anchor))continue;const arr=data.filter(d=>Math.abs(Date.parse(d.date)-anchor)<=15*DAY&&d.date<selectedDate);if(arr.length>=25)eligible.push(arr);}
 if(eligible.length<3)return {status:'blocked',reason:'Need ≥3 prior years, each with ≥25 valid days in a ±15-day seasonal window.'};
 const values=eligible.flat().map(d=>d.y).sort((a,b)=>a-b),med=median(values),mad=median(values.map(x=>Math.abs(x-med))),pct=(values.filter(x=>x<target.y).length+.5*values.filter(x=>x===target.y).length)/values.length,q95=values[Math.ceil(.95*values.length)-1];
 return {status:'available',years:eligible.length,days:values.length,rate:target.y,percentile:pct*100,rank_method:'midrank',threshold95:q95,median:med,robust_z:mad>0?.6745*(target.y-med)/mad:null,unusual:target.y>q95,reference:'VIIRS occupied-cell fraction; descriptive, not a forecast'};
}
const api={VERSION,csv,isoDate,normalize,ingest,inside,project,cell,center,keep,dates,analyze,distance,neighbors,recurrence,validateMetrics,calibrate,seasonal,median};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.FalconiaCore=api;
})(typeof globalThis!=='undefined'?globalThis:this);
