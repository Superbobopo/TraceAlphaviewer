/* Affichage partage entre le rapport React et le secours HTML autonome. */
(function (scope) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? '—' : Number(value).toLocaleString('fr-FR', {minimumFractionDigits:1, maximumFractionDigits:1});
  const signed = value => value == null ? '—' : `${value > 0 ? '+' : ''}${number(value)}`;
  const severity = group => group.field_severity || group.severity;
  const severityLabel = group => ({error:'Critique',warning:'Alerte',info:'Info'}[severity(group)] || 'Info');
  const action = group => group.field_action || group.action || group.title;
  const colors = {length:'#A78BFA',width:'#14B8A6',height:'#FDE047'};
  const list = values => `<ul>${(values || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul>`;
  const exclusionLabels = {orientation:'orientations différentes',invalid:'mesures invalides',incomplete:'mesures incomplètes',reference_absent:'références absentes',ambiguous:'identités ambiguës'};
  function biasText(bias) {
    return bias ? `Décalage régulier autour de ${signed(bias.median)} mm : ${number(bias.percent)} %, ${bias.count} boîtes, ${bias.references} références. ${bias.advice}` : '';
  }
  function direction(name, value) {
    if (!value) return 'Sans biais moyen';
    const labels = {length:['trop court','trop long'],width:['trop étroit','trop large'],height:['trop bas','trop haut']};
    return `${number(Math.abs(value))} mm ${labels[name][value > 0 ? 1 : 0]}`;
  }
  function measurementHtml(summary) {
    const axes = Object.entries(summary?.axes || {});
    if (!axes.length) return '<p class="muted">Mesures indisponibles.</p>';
    const excluded = Object.entries(summary.excluded || {}).filter(([,n]) => n).map(([key,n]) => `${exclusionLabels[key] || key} : ${n}`).join(' · ');
    return `<p class="muted">Dernière mesure complète par cycle de boîte. Écart = mesure − BdD. Tolérance ±${summary.tolerance_mm} mm.</p><div class="axis-grid">${axes.map(([name,axis]) => `<article class="axis" style="--axis:${colors[name]}"><h3>${esc(axis.label)}</h3><div class="metric">${signed(axis.all.mean_signed)} <small>mm</small></div><p>${axis.all.count ? esc(direction(name,axis.all.mean_signed)) : 'Aucune mesure comparable'}</p><p class="muted">${axis.all.outside_count} / ${axis.all.count} hors tolérance (${number(axis.all.outside_percent)} %)</p><div class="table-wrap"><table><thead><tr><th>Erreur absolue (mm)</th><th>Anomalies</th><th>Toutes</th></tr></thead><tbody>${[['Effectif','count'],['Références','references'],['Minimum','min_abs'],['Maximum','max_abs'],['Moyenne','mean_abs'],['Moyenne signée','mean_signed']].map(([label,key]) => `<tr><td>${label}</td><td>${key==='count'||key==='references'?axis.anomalies[key]:number(axis.anomalies[key])}</td><td>${key==='count'||key==='references'?axis.all[key]:number(axis.all[key])}</td></tr>`).join('')}</tbody></table></div>${axis.bias?`<p class="bias">${esc(biasText(axis.bias))}</p>`:''}</article>`).join('')}</div>${excluded?`<p class="muted">Exclus du bilan de réglage : ${esc(excluded)}.</p>`:''}`;
  }
  function sampleHtml(sample, connected) {
    const measures = sample.measured ? `<div class="table-wrap"><table><thead><tr><th>Dimension</th><th>BdD</th><th>Mesure</th><th>Écart</th></tr></thead><tbody>${[['Longueur T4/C6',2],['Largeur T5/C9',0],['Hauteur T5/LzB',1]].map(([label,i]) => `<tr><td>${label}</td><td>${sample.expected[i]} mm</td><td>${sample.measured[i]} mm</td><td>${signed(sample.deltas[i])} mm</td></tr>`).join('')}</tbody></table></div>` : `<p>${esc(sample.detail)}</p>`;
    return `<article class="sample"><div class="sample-head"><strong>${esc(sample.time_str)} · L.${sample.line}</strong><button class="small" data-navigate="${esc(sample.id)}" ${connected?'':'disabled'}>Voir dans AlphaViewer</button></div><p class="muted">${esc([sample.box,sample.barcode].filter(Boolean).join(' · '))}${sample.invalid?' · Mesure invalide, exclue du bilan':''}${sample.final===false?' · Mesure antérieure, hors effectif final':''}</p>${measures}<details><summary>Contexte de la trace</summary><pre>${esc((sample.context||[]).map(row => `L.${row.line}  ${row.text}`).join('\n') || 'Contexte indisponible.')}</pre></details></article>`;
  }
  function mount(root, data) {
    const groups = data.groups || [];
    const indexed = groups.map(group => ({group,search:JSON.stringify(group).toLocaleLowerCase('fr')}));
    const state = {search:'',family:'all',level:'all',pages:{},open:new Set(),connected:false,message:''};
    const local = location.protocol==='http:' && location.hostname==='127.0.0.1' && /\/view\.html$/.test(location.pathname);
    const controller = new AbortController();
    let disposed = false, debounce;
    function render() {
      root.querySelectorAll('details[data-open]').forEach(node => node.open ? state.open.add(node.dataset.open) : state.open.delete(node.dataset.open));
      const filtered = indexed.filter(({group,search}) => (state.family==='all'||group.family===state.family) && (state.level==='all'||severity(group)===state.level) && (!state.search||search.includes(state.search.toLocaleLowerCase('fr')))).map(x => x.group);
      const counts = data.counts || {};
      const source = data.source || {};
      root.innerHTML = `<main class="report"><header class="hero"><div><div class="eyebrow">TraceAlphaViewer · diagnostic terrain</div><h1>Comprendre cette trace</h1><p>${esc(source.name || 'Trace analysée')}</p><p class="muted">${esc(source.start)} → ${esc(source.end)} · ${esc(source.duration)} · Généré le ${esc(data.generated_at)}</p></div><div><div class="actions"><button class="primary" data-pdf>Exporter PDF</button></div><p class="status" role="status">${esc(state.message || (state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'Consultation autonome · navigation viewer indisponible.'))}</p></div></header><div class="summary-grid">${[['Types critiques',counts.error || 0],['Types en alerte',counts.warning || 0],['Boîtes analysées',counts.analyzed_boxes || 0],['Types de problèmes',counts.types || 0]].map(([label,value])=>`<div class="stat"><span class="muted">${label}</span><strong>${value}</strong></div>`).join('')}</div><section class="section"><h2>${esc(data.verdict?.title || 'Synthèse')}</h2><p>${esc(data.verdict?.text)}</p><p class="muted">${counts.incidents || 0} diagnostics regroupés · ${counts.info || 0} types informatifs. Cliquer sur un problème pour consulter ses chiffres, les contrôles et les exemples.</p><div class="actions">${(data.priority || []).slice(0,5).map(group=>`<button class="small" data-priority="${esc(group.id)}">${esc(group.title)} · ${esc(group.affected_label || group.metric)}</button>`).join('')}</div></section><details class="section" data-open="measurements" ${state.open.has('measurements')?'open':''}><summary>Bilan des mesures <span class="muted">${data.measurements?.comparable_count || 0} boîtes comparables · longueur, largeur, hauteur</span></summary>${measurementHtml(data.measurements)}</details>${cameraHtml(data.camera,state.open.has('camera'))}<div class="filters"><input type="search" aria-label="Rechercher un diagnostic" placeholder="Code, référence, boîte, problème…" value="${esc(state.search)}"><select aria-label="Niveau" data-level>${[['all','Tous les niveaux'],['error','Critiques'],['warning','Alertes'],['info','Informations']].map(([key,label])=>`<option value="${key}" ${state.level===key?'selected':''}>${label}</option>`).join('')}</select><select aria-label="Famille" data-family>${(data.families || []).filter(item=>item.id!=='critical').map(item=>`<option value="${item.id}" ${state.family===item.id?'selected':''}>${esc(item.label)}</option>`).join('')}</select></div><h2 id="problems">${filtered.length} type(s) de problème</h2>${filtered.map(group=>groupHtml(group,state)).join('') || '<div class="empty">Aucun diagnostic pour ces critères.</div>'}<details class="section" data-open="zones" ${state.open.has('zones')?'open':''}><summary>Répartition par zone</summary>${list((data.zones||[]).map(zone=>`${zone.label || zone.family} : ${zone.occurrences} occurrences, ${zone.errors} critiques, ${zone.warnings} alertes`))}</details><p class="footer">Les constats proviennent de la trace. Les causes proposées et les pistes de calibrage restent à confirmer sur la machine. Les exemples antérieurs sont conservés sans compter plusieurs fois la même boîte.</p></main>`;
    }
    function refreshStatus() {
      root.querySelectorAll('[data-navigate]').forEach(button => button.disabled=!state.connected);
      const label = root.querySelector('.status');
      if(label) label.textContent = state.message || (state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'La trace source est fermée ou la liaison est indisponible.');
    }
    async function status() {
      if(!local || disposed) return;
      try { const response=await fetch('status',{signal:controller.signal}); state.connected=response.ok && (await response.json()).connected; }
      catch { state.connected=false; }
      if(!disposed) refreshStatus();
    }
    async function click(event) {
      const button=event.target.closest('button'); if(!button) return;
      if(button.hasAttribute('data-pdf')) {downloadPdf(data);return;}
      if(button.dataset.navigate) {
        button.disabled=true;state.message='Recherche de cet exemple dans AlphaViewer…';refreshStatus();
        try {const response=await fetch('navigate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sample_id:button.dataset.navigate}),signal:controller.signal});const result=await response.json();state.message=result.ok?`AlphaViewer positionné à la ligne ${result.line}.`:(result.error || 'Navigation indisponible.');}
        catch {state.message='La trace source est fermée ou remplacée. Rouvrir le rapport depuis la bonne trace.';state.connected=false;}
        if(!disposed) refreshStatus();return;
      }
      if(button.dataset.priority) {
        state.family='all';state.level='all';state.search='';render();
        const card=[...root.querySelectorAll('details[data-group]')].find(node=>node.dataset.group===button.dataset.priority);
        if(card){card.open=true;card.scrollIntoView({behavior:'smooth',block:'start'});}return;
      }
      if(button.dataset.pageGroup) {state.pages[button.dataset.pageGroup]=Number(button.dataset.page);render();}
    }
    function input(event) {
      if(event.target.matches('input[type=search]')) {
        state.search=event.target.value;clearTimeout(debounce);
        debounce=setTimeout(()=>{const pos=event.target.selectionStart;render();const field=root.querySelector('input[type=search]');field.focus();try{field.setSelectionRange(pos,pos);}catch{}},180);
      } else if(event.target.matches('[data-family],[data-level]')) {
        state[event.target.hasAttribute('data-family')?'family':'level']=event.target.value;render();
      }
    }
    root.addEventListener('click',click);root.addEventListener('input',input);
    render();status();const timer=setInterval(status,10000);
    return ()=>{disposed=true;controller.abort();clearTimeout(debounce);clearInterval(timer);root.removeEventListener('click',click);root.removeEventListener('input',input);};
  }
  function cameraHtml(camera, open=false) {
    if(!camera?.available)return '';
    const max=Math.max(1,...(camera.chart||[]).map(row=>row.success_count));
    return `<details class="section" data-open="camera" ${open?'open':''}><summary>Lecture des caméras <span class="muted">${esc(camera.note)}</span></summary>${(camera.chart||[]).map(row=>`<div class="camera-row"><span>${esc(row.label)}</span><div class="bar"><i class="${row.status==='zero'?'zero':''}" style="width:${100*row.success_count/max}%"></i></div><strong>${row.success_count} lectures</strong></div><p class="muted">${esc(row.label)} : ${esc(row.status_label)}</p>`).join('')}<div class="table-wrap"><table><thead><tr><th>Lecteur</th><th>Caméras attendues</th><th>Boîtes</th><th>Lectures à 0 code</th></tr></thead><tbody>${(camera.reader_stats||[]).map(row=>`<tr><td>${esc(row.reader)}</td><td>${esc(row.expected_cameras)}</td><td>${row.boxes}</td><td>${esc(row.zero_code_label)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }
  function groupHtml(group,state) {
    const examples=group.examples||[],page=state.pages[group.id];
    const selected=page==null?examples.filter(s=>(group.representative_ids||[]).includes(s.id)):examples.slice(page*25,page*25+25);
    const pagination=examples.length>3?`<div class="pagination">${page==null?`<button data-page-group="${esc(group.id)}" data-page="0">Voir les ${examples.length} exemples</button>`:`<button data-page-group="${esc(group.id)}" data-page="${Math.max(0,page-1)}" ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1} / ${Math.ceil(examples.length/25)}</span><button data-page-group="${esc(group.id)}" data-page="${page+1}" ${(page+1)*25>=examples.length?'disabled':''}>Suivants</button>`}</div>`:'';
    return `<details class="group ${severity(group)}" data-group="${esc(group.id)}" data-open="${esc(group.id)}" ${state.open.has(group.id)?'open':''}><summary><div><div class="badges"><span class="badge ${severity(group)}">${severityLabel(group)}</span><span class="badge">${esc(group.field_zone_label || group.family_label)}</span><span class="badge">${esc(group.code)}</span></div><h3>${esc(group.title)}</h3><p>${esc(group.affected_label || group.metric)} · ${esc(action(group))}</p><p class="muted">${esc(group.evidence)}</p></div></summary><div class="group-body"><section><h3>Constat et chiffres</h3><p>${esc(group.field_explanation || group.field_impact || group.impact)}</p><p>${esc(group.symptom)}</p>${list(group.business_lines)}<p class="muted">${group.incident_count} diagnostics · Confiance : ${esc(group.confidence)}</p>${Object.keys(group.measurement_stats || {}).length?measurementHtml(group.measurement_stats):''}</section><div class="columns"><section><h3>Causes possibles</h3>${list(group.probable_causes)}</section><section><h3>Contrôles conseillés</h3>${list(group.checks)}</section></div><section class="evidence"><h3>Exemples réels <span class="muted">${examples.length} preuve(s) collectée(s)</span></h3>${selected.map(sample=>sampleHtml(sample,state.connected)).join('') || '<p class="muted">Aucun exemple individuel disponible.</p>'}${pagination}</section><details><summary>Détail complet des diagnostics regroupés</summary>${(group.incidents||[]).map(item=>`<article class="sample"><strong>${esc(item.start_time_str)} → ${esc(item.end_time_str)} · L.${item.first_line} à L.${item.last_line}</strong><p>${esc(item.title)} · ${item.count} occurrence(s) · ${esc(item.duration)}</p><p>${esc(item.summary)}</p><p>${esc(item.symptom)}</p><p class="muted">Confiance : ${esc(item.confidence)}</p>${list(item.probable_causes)}${list(item.checks)}</article>`).join('')}</details></div></details>`;
  }
  function pdfLines(data) {
    const result=[];
    const add=(text,kind='text')=>result.push({text:String(text??''),kind});
    add(data.source?.name || 'Trace analysée','title');
    add(`${data.source?.start || ''} → ${data.source?.end || ''} · ${data.source?.duration || ''} · Généré le ${data.generated_at}`);
    add(data.verdict?.title || 'Synthèse','section');add(data.verdict?.text);
    add(`${data.counts?.analyzed_boxes || 0} boîtes analysées · ${data.counts?.error || 0} types critiques · ${data.counts?.warning || 0} types en alerte · ${data.counts?.info || 0} types informatifs`,'metric');
    add('Bilan des mesures','section');
    for(const [name,axis] of Object.entries(data.measurements?.axes || {})) {
      add(axis.label,'group');
      for(const [key,label] of [['anomalies','Anomalies'],['all','Toutes les mesures comparables']]) {
        const s=axis[key];add(`${label} : ${s.count} boîtes, ${s.references} références.`);
        add(`Erreur absolue : min ${number(s.min_abs)}, max ${number(s.max_abs)}, moyenne ${number(s.mean_abs)} mm.`);
        add(`Décalage moyen : ${signed(s.mean_signed)} mm${s.count?' ('+direction(name,s.mean_signed)+')':''}.`);
      }
      add(`Hors tolérance : ${axis.all.outside_count} (${number(axis.all.outside_percent)} %).`);
      if(axis.bias)add(biasText(axis.bias));
    }
    const excluded=Object.entries(data.measurements?.excluded||{}).filter(([,n])=>n).map(([key,n])=>`${exclusionLabels[key]||key} : ${n}`).join(' ; ');
    if(excluded)add('Exclus du bilan : '+excluded);
    if(data.camera?.available){add('Lecture des caméras','section');add(data.camera.note);for(const row of data.camera.chart||[])add(`${row.label} : ${row.success_count} lectures réussies — ${row.status_label}`);for(const row of data.camera.reader_stats||[])add(`${row.reader} : ${row.zero_code_label} lectures à 0 code ; caméras ${row.expected_cameras}`);}
    add('Diagnostics et contrôles prioritaires','section');
    for(const group of data.groups||[]) {
      add(`[${severityLabel(group)}] ${group.title}`,'group');add(`${group.affected_label || group.metric} · ${group.evidence}`);add(group.field_explanation||group.impact);add(group.summary);
      add('Action : '+action(group));for(const cause of group.probable_causes||[])add('Cause possible : '+cause);for(const check of group.checks||[])add('Contrôle : '+check);
      const samples=(group.examples||[]).filter(s=>(group.representative_ids||[]).includes(s.id));
      for(const sample of samples){add(`Exemple ${sample.time_str} · L.${sample.line} · ${sample.box||''} ${sample.barcode||''}`,'example');if(sample.measured){for(const [label,i] of [['Longueur',2],['Largeur',0],['Hauteur',1]])add(`${label} : BdD ${sample.expected[i]} mm ; mesure ${sample.measured[i]} mm ; écart ${signed(sample.deltas[i])} mm.`);}else add(sample.detail);for(const row of sample.context||[])add(`L.${row.line} ${row.text}`);}
    }
    return result;
  }
  /* PDF vectoriel autonome : accents WinAnsi, retours et fonds dimensionnes. */
  function buildPdf(data) {
    const encode=text=>String(text).replace(/→/g,'->').replace(/[−–—]/g,'-').replace(/’/g,"'").replace(/œ/g,'oe').replace(/[^\x20-\x7e\xa0-\xff]/g,' ');
    const escape=text=>encode(text).replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)');
    const text=(value,x,y,size,bold=false)=>`BT /${bold?'F2':'F1'} ${size} Tf ${x} ${y} Td (${escape(value)}) Tj ET\n`;
    const wrap=(value,max)=>{const words=encode(value).split(/\s+/);const lines=[];let line='';for(let word of words){while(word.length>max){if(line){lines.push(line);line='';}lines.push(word.slice(0,max));word=word.slice(max);}if((line+' '+word).trim().length>max){lines.push(line);line=word;}else line=(line+' '+word).trim();}if(line)lines.push(line);return lines.length?lines:[''];};
    const pages=[];let body='',y=745;
    const header=()=>{body+='q 0.07 0.17 0.29 rg 36 778 523 42 re f Q\nq 1 1 1 rg\n'+text('TraceAlphaViewer — Rapport diagnostic',48,794,15,true)+'Q\n';};
    const finish=()=>{body+=text(`TraceAlphaViewer | page ${pages.length+1}`,42,28,8);pages.push(body);body='';y=745;header();};header();
    for(const item of pdfLines(data)) {
      const size=item.kind==='title'?16:item.kind==='section'?13:item.kind==='group'?11:9;
      const bold=item.kind!=='text';const lines=wrap(item.text,Math.floor(480/(size*.55)));
      const gap=size+5;const height=lines.length*gap+10;
      if(y-height<55 && height<680)finish();
      if(item.kind==='section'||item.kind==='group'||item.kind==='metric'){body+=`q ${item.kind==='section'?'0.88 0.93 0.98':'0.95 0.96 0.98'} rg 38 ${y-height+3} 519 ${height} re f Q\n`;}
      for(const line of lines){if(y-gap<55)finish();body+=text(line,48,y-gap+4,size,bold);y-=gap;}y-=10;
    }
    finish();const objects=[];const add=value=>(objects.push(value),objects.length);
    const f1=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>');const f2=add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>');const ids=[];
    for(const page of pages){const stream=add(`<< /Length ${page.length} >>\nstream\n${page}endstream`);ids.push(add(`<< /Type /Page /Parent PARENT 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 ${f1} 0 R /F2 ${f2} 0 R >> >> /Contents ${stream} 0 R >>`));}
    const parent=add(`<< /Type /Pages /Kids [${ids.map(id=>`${id} 0 R`).join(' ')}] /Count ${ids.length} >>`);const catalog=add(`<< /Type /Catalog /Pages ${parent} 0 R >>`);for(const id of ids)objects[id-1]=objects[id-1].replace('PARENT',parent);
    let pdf='%PDF-1.4\n';const offsets=[0];objects.forEach((object,index)=>{offsets.push(pdf.length);pdf+=`${index+1} 0 obj\n${object}\nendobj\n`;});const offset=pdf.length;pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`;offsets.slice(1).forEach(value=>pdf+=String(value).padStart(10,'0')+' 00000 n \n');pdf+=`trailer\n<< /Size ${objects.length+1} /Root ${catalog} 0 R >>\nstartxref\n${offset}\n%%EOF`;
    return Uint8Array.from(pdf,c=>c.charCodeAt(0));
  }
  function downloadPdf(data) {
    const blob=new Blob([buildPdf(data)],{type:'application/pdf'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='diagnostic-terrain.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  scope.TraceReport={mount,buildPdf,pdfLines};
})(globalThis);
