/* Affichage partage entre le rapport React et le secours HTML autonome. */
(function (scope) {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? '—' : Number(value).toLocaleString('fr-FR', {minimumFractionDigits:1, maximumFractionDigits:1});
  const signed = value => value == null ? '—' : `${value > 0 ? '+' : ''}${number(value)}`;
  const severity = group => group.field_severity || group.severity;
  const referenceRejection = code => ['REFERENCE_ABSENT','REFERENCE_NON_ALPHATISABLE'].includes(code);
  const structuredProof = code => referenceRejection(code) || ['C2_SIGNAL_ANOMALY','C3_SIGNAL_ANOMALY'].includes(code);
  const criticalRobot = group => Number(group?.metrics?.day?.count||0)>=10;
  const severityLabel = group => ({error:'Critique',warning:'Alerte',info:'Info'}[severity(group)] || 'Info');
  const action = group => group.field_action || group.action || group.title;
  const colors = {length:'#A78BFA',width:'#14B8A6',height:'#FDE047'};
  const axisInfo = {length:{label:'Longueur',source:'T4/C6 · T4C',under:'Trop courtes',over:'Trop longues'},width:{label:'Largeur',source:'T5/C9',under:'Trop étroites',over:'Trop larges'},height:{label:'Hauteur',source:'T5/LzB',under:'Trop basses',over:'Trop hautes'}};
  const axisTolerance = (summary,name) => summary?.tolerances_mm?.[name] ?? summary?.axes?.[name]?.tolerance_mm ?? summary?.tolerance_mm ?? 3;
  const thresholdText = summary => `Seuils d’alerte (écart absolu) : longueur > ${axisTolerance(summary,'length')} mm · largeur > ${axisTolerance(summary,'width')} mm · hauteur > ${axisTolerance(summary,'height')} mm.`;
  const isPrimary = row => row.display_primary ?? (row.total>0 && row.count*10>=row.total);
  const primaryRows = (data,axis,side) => (data?.measurement_references?.[axis]?.[side]||[]).filter(isPrimary);
  const displayExtreme = (data,axis,side) => {const rows=primaryRows(data,axis,side);return rows.length?extreme(rows[0].worst):data?.measurements?.axes?.[axis]?.anomalies?.[side+'_count']?'Aucun produit à 10 %':'Aucune';};
  const fullMeasurement = sample => Number.isInteger(sample.display_frame_index) && sample.display_frame_index>=0 && sample.display_line>0 && ['length','width','height'].every(axis=>sample.sources?.[axis]>0) && sample.measured?.length===3 && sample.measured.every(value=>value>0) && sample.expected?.length===3 && sample.expected.every(value=>value>0);
  const list = values => `<ul>${(values || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul>`;
  const exclusionLabels = {orientation:'orientations probables',orientation_uncertain:'orientations indécidables',camera_unconfirmed:'identifications caméra non confirmées',invalid:'mesures invalides',incomplete:'mesures incomplètes',reference_absent:'références BdD absentes',ambiguous:'identités ambiguës',unknown:'UNKNOWN sans produit identifié',identity_unconfirmed:'identifications non confirmées',reference_conflict:'références contradictoires',t4c_absent:'longueur T4C absente'};
  function biasText(bias) {
    return bias ? `Décalage régulier autour de ${signed(bias.median)} mm : ${number(bias.percent)} %, ${bias.count} boîtes, ${bias.references} références. ${bias.advice}` : '';
  }
  const hasRepeatedOffsets = axis => Object.values(axis.recurrence || {}).some(item => item.cluster?.similar);
  function recurrenceEntries(axis) {
    return ['under','over'].map(side=>{
      const item=axis.recurrence?.[side],cluster=item?.cluster,frequent=item?.frequencies?.[0];
      if(!frequent)return null;
      const sign=side==='under'?'en moins':'en trop';
      const text=cluster?`${cluster.bad_count} boîtes en défaut autour de ${signed(cluster.center)} mm ${sign} (±1 mm). ${cluster.similar?`Répétition sur ${cluster.repeated_references} produit(s).`:'Répétition par produit non confirmée.'}${cluster.limited?' Effectif limité.':''}`:`Écart le plus fréquent ${sign} : ${signed(frequent.delta)} mm, ${frequent.count} boîte(s). Répétition par produit non confirmée.`;
      return {side,count:cluster?.bad_count??item.count,text};
    }).filter(Boolean);
  }
  const recurrenceBrief = axis => recurrenceEntries(axis).map(item=>item.text);
  function recurrenceHtml(axis) {
    const brief=recurrenceBrief(axis);if(!brief.length)return '';
    return `<div class='recurrence'><strong>${hasRepeatedOffsets(axis)?'Répétition observée':'Écarts observés'}</strong>${brief.map(text=>`<p>${esc(text)}</p>`).join('')}</div>`;
  }
  function recurrenceDetailsHtml(axis,name) {
    const content=['under','over'].map(side=>{
      const item=axis.recurrence?.[side],cluster=item?.cluster;if(!cluster)return '';
      return `<section><h4>${side==='under'?'Écarts en moins':'Écarts en trop'}</h4><p><strong>Groupe le plus fréquent :</strong> autour de ${signed(cluster.center)} mm, avec une marge de ±1 mm. ${cluster.count} mesures de ${cluster.references} produits sur ${axis.all.count} comparables (${number(cluster.percent_all)} %), de ${signed(cluster.min_signed)} à ${signed(cluster.max_signed)} mm.</p><p><strong>Défauts et voisines conformes :</strong> ${cluster.bad_count} mesures dépassent le seuil de cet axe ; ${cluster.good_count} restent conformes. Ces défauts représentent ${number(cluster.percent_side)} % des ${item.count} défauts de ce côté, ${number(cluster.percent_bad)} % des ${axis.anomalies.count} défauts de cet axe et ${number(cluster.bad_percent_all)} % des ${axis.all.count} comparables.</p><p><strong>Répétition par produit :</strong> ${cluster.repeated_references} produit(s) ont au moins deux mesures, dont au moins 80 % sont à ±1 mm de ce centre, pour une même variante BdD. ${cluster.shared?'La répétition est étayée sur plusieurs produits.':cluster.similar?'La répétition concerne un seul produit.':'La répétition par produit n’est pas confirmée.'}${cluster.limited?' Effectif limité.':''}</p>${cluster.dominant?`<p><strong>Produit le plus représenté :</strong> ${esc(cluster.dominant.barcode)}, ${cluster.dominant.count}/${cluster.count} mesures du groupe (${number(cluster.dominant.percent)} %).</p>`:''}<p><strong>Écarts fréquents :</strong> ${item.frequencies.slice(0,5).map(row=>`${row.count} boîtes à ${signed(row.delta)} mm`).join(' ; ')}.</p>${cluster.advice?`<p><strong>Premier contrôle :</strong> ${esc(cluster.advice)}</p>`:''}<button class='small' data-measure-axis='${name}' data-measure-side='${side}_group'>Voir les produits autour de ${signed(cluster.center)} mm</button></section>`;
    }).join('');
    return content?`<details class='recurrence-details' data-open='recurrence-${name}'><summary>Comment les répétitions sont calculées</summary>${content}</details>`:'';
  }
  function groupRecurrenceHtml(group) {
    const names={T4_LENGTH:['length'],T5_WIDTH:['width'],T5_HEIGHT:['height'],GLOBAL:['length','width','height']}[group.code]||[];
    const rows=names.flatMap(name=>{const axis=group.measurement_stats?.axes?.[name];return axis?recurrenceEntries(axis).map(item=>({...item,name})):[];});
    rows.sort((a,b)=>b.count-a.count||['length','width','height'].indexOf(a.name)-['length','width','height'].indexOf(b.name)||['under','over'].indexOf(a.side)-['under','over'].indexOf(b.side));
    return rows.length?`<div class='trace-measurement-summary'><p class='muted'>Observations sur toutes les boîtes comparables de la trace.</p>${rows.map(item=>`<p class='group-recurrence'><strong>${axisInfo[item.name].label}</strong> · ${esc(item.text)}</p>`).join('')}</div>`:'';
  }
  function distributionHtml(axis,name,expanded=false) {
    const rows=axis.frequencies || [];
    if(!rows.length)return '';
    const visible=expanded?rows:rows.slice(0,5),limited=rows.length>5;
    const share=visible.reduce((sum,row)=>sum+row.percent,0);
    return `<div class='distribution' data-distribution='${name}'><h4>Répartition de toutes les mesures comparables</h4><p class="muted">Les mesures conformes sont incluses. Chaque boîte est comptée une fois.</p>${limited?`<p class='distribution-caption'>${expanded?`${rows.length} écarts observés · liste complète`:`Les 5 écarts les plus fréquents · ${number(share)} % des boîtes comparables`}</p>`:''}<div class="table-wrap"><table id='distribution-${name}' class="measurement-distribution"><thead><tr><th>Écart signé</th><th>Boîtes</th><th>Part des comparables</th></tr></thead><tbody>${visible.map(row=>`<tr><td>${signed(row.delta)} mm</td><td>${row.count}</td><td>${number(row.percent)} %</td></tr>`).join('')}</tbody></table></div>${limited?`<button class='distribution-toggle' data-distribution-axis='${name}' aria-expanded='${expanded}' aria-controls='distribution-${name}'>${expanded?'Réduire la liste':`Afficher toute la répartition (${rows.length} écarts)`}<svg aria-hidden='true' viewBox='0 0 16 16' width='16' height='16' fill='none' stroke='currentColor' stroke-width='1.6'><path d='${expanded?'M4 10l4-4 4 4':'M4 6l4 4 4-4'}'/></svg></button>`:''}</div>`;
  }
  function observationText(row) {
    const expected=row.expected || [];
    const values=`BdD ${expected[2]} × ${expected[0]} × ${expected[1]} mm (longueur × largeur × hauteur) : ${row.total} mesures, plage ${signed(row.min_signed)} à ${signed(row.max_signed)} mm.`;
    const nearby=row.center==null?'':` ${row.close_count}/${row.total} (${number(row.close_percent)} %) à ±1 mm autour de ${signed(row.center)} mm.`;
    const conclusion=row.repeated?' Écarts proches sur ce produit.':row.total===1?' Une seule mesure : la répétition n’est pas confirmée.':'';
    const spread=row.dispersed?` Dispersion observée sur ce produit : la fenêtre de 2 mm la plus fournie contient ${row.window_count}/${row.total} mesures (${number(row.window_percent)} %).`:'';
    return values+nearby+conclusion+spread+(row.limited?' Effectif limité.':'');
  }
  function productObservationHtml(row,state,axis) {
    const observations=row?.observations||[];if(!observations.length)return '';
    const representatives=(row.representative_ids||[]).map(id=>state.measurementExamples.get(id)).filter(Boolean);
    return `<details class='product-observations' data-open='product-${axis}-${esc(row.barcode)}'><summary>Répétitions et variantes de ce produit</summary>${observations.length>1?'<p class=variant-note>Plusieurs dimensions BdD : les variantes sont analysées séparément.</p>':''}${observations.map(item=>`<p>${esc(observationText(item))}</p>`).join('')}${representatives.length?`<details class='comparison-examples'><summary>Exemples représentatifs, avec les conformes voisines</summary>${representatives.map(sample=>sampleHtml(sample,state.connected,axis,state.tolerances)).join('')}</details>`:''}</details>`;
  }
  function direction(name, value) {
    if (!value) return 'Sans biais moyen';
    const labels = {length:['trop court','trop long'],width:['trop étroit','trop large'],height:['trop bas','trop haut']};
    return `${number(Math.abs(value))} mm ${labels[name][value > 0 ? 1 : 0]}`;
  }
  function measurementHtml(summary,data,state) {
    const axes=['length','width','height'].filter(name=>summary?.axes?.[name]);if(!axes.length)return '<p>Aucune analyse de mesure disponible.</p>';
    const excluded=Object.entries(summary.excluded||{}).filter(([,count])=>count);
    return `<div class='measurement-intro'><p>${esc(globalMeasurementText(summary))}</p><p class='muted'>${esc(measurementTotal(summary))}</p><p class='muted'>Une boîte compte une fois. La mesure Alpha est comparée à la BdD du même produit.</p><p class='muted'>${esc(thresholdText(summary))}</p></div><div class='axis-grid'>${axes.map(name=>{
      const axis=summary.axes[name],bad=axis.anomalies,info=axisInfo[name];
      return `<article class='axis' data-axis='${name}' style='--axis:${colors[name]}'><div class='axis-heading'><h3>${info.label}</h3><span class='muted'>${info.source}</span></div><p class='axis-count'>${axis.all.count?`<strong>${bad.count}</strong> boîtes hors tolérance`:'Comparaison indisponible'}</p><p class='muted'>${axis.all.count?`sur ${axis.all.count} comparables · ${number(axis.all.outside_percent)} %`:'Aucune boîte comparable'}</p><p class='axis-threshold'><strong>À vérifier : écart > ${axisTolerance(summary,name)} mm</strong> en valeur absolue.</p><div class='measure-directions'>${['under','over'].map(side=>`<button data-measure-axis='${name}' data-measure-side='${side}' ${bad[side+'_count']?'':'disabled'}><span>${info[side]} · ${bad[side+'_count']}</span><small>Écart marquant (produits ≥ 10 %) : ${displayExtreme(data,name,side)}</small></button>`).join('')}</div><p class='muted'>Produits concernés : ${bad.references} sur ${axis.all.references} produits distincts comparables.</p>${recurrenceHtml(axis)}${distributionHtml(axis,name,state.distributions.has(name))}<details class='measure-details' data-open='stats-${name}'><summary>Statistiques et explications</summary><p>${esc(measurementCounts(axis))}</p><p>Décalage moyen : <strong>${signed(bad.mean_signed)}${bad.count?' mm':''}</strong> · Erreur moyenne : <strong>${number(bad.mean_abs)}${bad.count?' mm':''}</strong></p><p class='muted'>Ces moyennes portent sur les mauvaises mesures. Le décalage compense les signes opposés ; l’erreur moyenne indique leur amplitude sans signe. Elles ne déterminent pas une correction de réglage.</p><div class='table-wrap'><table><thead><tr><th>Indicateur</th><th>Hors tolérance</th><th>Toutes les comparables</th></tr></thead><tbody>${[['Boîtes','count'],['Produits distincts','references'],['Écart minimum (mm)','min_signed'],['Écart maximum (mm)','max_signed'],['Décalage moyen (mm)','mean_signed'],['Erreur moyenne (mm)','mean_abs'],['Erreur absolue minimum (mm)','min_abs'],['Erreur absolue maximum (mm)','max_abs']].map(([label,key])=>`<tr><td>${label}</td><td>${['count','references'].includes(key)?bad[key]:key.includes('signed')?signed(bad[key]):number(bad[key])}</td><td>${['count','references'].includes(key)?axis.all[key]:key.includes('signed')?signed(axis.all[key]):number(axis.all[key])}</td></tr>`).join('')}</tbody></table></div>${recurrenceDetailsHtml(axis,name)}${axis.bias&&!hasRepeatedOffsets(axis)?`<p>${esc(biasText(axis.bias))}</p>`:''}${axis.interpretation?.length?`<h4>Pistes à confirmer</h4>${list(axis.interpretation)}`:''}</details></article>`;
    }).join('')}</div>${data&&state?referenceHtml(data,state):''}<details class='measurement-exclusions'><summary>Boîtes non comparées · ${summary.excluded_count||0}</summary><p>Ces boîtes ne sont comptées ni conformes ni hors tolérance. Reconnaissance CB1/CB2 et dimensions fiables sont nécessaires ; le sens doit être compatible avec les mesures.</p>${excluded.length?`<ul>${excluded.map(([key,count])=>`<li><strong>${count}</strong> · ${esc(exclusionLabels[key]||key)}</li>`).join('')}</ul>`:'<p>Aucune boîte exclue.</p>'}</details>`;
  }
  function referenceHtml(data,state) {
    const selected=state.measurementSelection;if(!selected)return '';
    const {axis,side,barcode,page}=selected,info=axisInfo[axis],grouped=side.endsWith('_group');
    const allRows=data.measurement_references?.[axis]?.[side]||[],row=allRows.find(item=>item.barcode===barcode);
    const rows=grouped?allRows:allRows.filter(isPrimary),rare=grouped?[]:allRows.filter(item=>!isPrimary(item));
    const items=barcode?(row?.sample_ids||[]).map(id=>state.measurementExamples.get(id)).filter(Boolean):rows;
    const visible=items.slice(page*25,(page+1)*25),rarePage=selected.rarePage||0;
    const center=data.measurements.axes[axis].recurrence?.[side.replace('_group','')]?.cluster?.center;
    const title=`${info.label} · ${grouped?`Écarts proches de ${signed(center)} mm`:info[side]}`;
    const table=values=>`<div class='table-wrap'><table><thead><tr><th>Produit / référence</th><th>Boîtes concernées</th><th>Pire écart</th></tr></thead><tbody>${values.map(item=>`<tr><td><strong>${esc(item.name||'Produit identifié')}</strong><br><button class='reference-link' data-measure-barcode='${esc(item.barcode)}'>${esc(item.barcode)}</button>${item.variant_count>1?'<p class=variant-note>Plusieurs variantes BdD</p>':''}</td><td>${item.count} sur ${item.total}<br><span class='muted'>${number(item.percent)} % des comparables de ce produit</span></td><td><strong>${signed(item.worst)} mm</strong></td></tr>`).join('')}</tbody></table></div>`;
    const rareHtml=!barcode&&rare.length?`<details class='rare-products' data-open='rare-${axis}-${side}'><summary>Cas rares (&lt; 10 %) · ${rare.length} produits</summary><p class='muted'>Ces défauts restent inclus dans tous les calculs. Le seuil de 10 % porte sur les boîtes comparables de chaque produit, pour ce côté.</p>${table(rare.slice(rarePage*25,(rarePage+1)*25))}<div class='pagination'><button class='small' data-measure-rare-page='${rarePage-1}' ${rarePage===0?'disabled':''}>Précédents</button><span>Page ${rarePage+1}/${Math.ceil(rare.length/25)} · ${rare.length} produits rares</span><button class='small' data-measure-rare-page='${rarePage+1}' ${(rarePage+1)*25>=rare.length?'disabled':''}>Suivants</button></div></details>`:'';
    return `<section class='measurement-reference-list' aria-label='Détail des mesures'><h3>${esc(title)}</h3><p class='muted'>${grouped?'Les mesures conformes voisines sont incluses.':`Liste principale : au moins 10 % de défauts de ce côté par produit. ${rows.length} produits retenus ; ${rare.length} produits dans les cas rares. Les totaux et distributions incluent tous les défauts.`}</p>${barcode?`<div class='product-heading'><div><h4>${esc(row?.name||'Produit identifié')}</h4><p class='muted'>Référence ${esc(barcode)}</p></div><button class='small' data-measure-back>Retour aux références</button></div><h4>${grouped?'Toutes les mesures comparables de ce produit':'Boîtes hors tolérance de ce côté'}</h4>`:''}${!items.length?`<p>${barcode||grouped?'Aucune boîte concernée.':'Aucun produit n’atteint 10 % de défauts de ce côté. Consulter les cas rares.'}</p>`:barcode?`<div class='reference-proofs'>${visible.map(sample=>sampleHtml(sample,state.connected,axis,state.tolerances)).join('')}</div>${productObservationHtml(row,state,axis)}`:table(visible)}<div class='pagination'><button class='small' data-measure-page='${page-1}' ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1}/${Math.max(1,Math.ceil(items.length/25))} · ${items.length} ${barcode?'boîtes':'produits'}</span><button class='small' data-measure-page='${page+1}' ${(page+1)*25>=items.length?'disabled':''}>Suivants</button><button class='small' data-measure-close>Fermer la liste</button></div>${rareHtml}</section>`;
  }
  const range = stats => stats?.count ? `${signed(stats.min_signed)} à ${signed(stats.max_signed)} mm` : 'Aucune mauvaise mesure';
  const extreme = value => value == null ? 'Aucune' : `${signed(value)} mm`;
  const measurementCounts = axis => axis.all.count ? `Bonnes mesures : ${axis.all.within_count}/${axis.all.count} (${number(axis.all.within_percent)} %) · Mauvaises mesures : ${axis.all.outside_count}/${axis.all.count} (${number(axis.all.outside_percent)} %)` : 'Aucune mesure comparable pour cet axe.';
  const measurementTotal = summary => `${summary.cycle_count || 0} cycles de boîtes analysés sur T5 · ${summary.comparable_count || 0} comparables · ${summary.excluded_count || 0} exclus`;
  const globalMeasurementText = summary => !summary.global?.count ? 'Aucune boîte ne réunit les conditions de comparaison. Consulter les boîtes non comparées.' : summary.global.outside_count ? `${summary.global.outside_count} boîtes hors tolérance sur ${summary.global.count} comparables (${number(summary.global.outside_percent)} %). Une boîte en défaut sur plusieurs dimensions compte une seule fois.` : `Les ${summary.global.count} boîtes comparables sont conformes sur les trois dimensions.`;
  function orientationMatchesHtml(sample) {
    if(sample.code!=='ORIENTATION')return '';
    const uncertain=sample.orientation_state==='orientation_uncertain';
    return `<div class='orientation-explanation'><p><strong>${uncertain?'Orientation indécidable':'Orientation probable d’après les dimensions'}</strong> · ${uncertain?'La présentation normale et une autre orientation obtiennent le même score.':'Une autre orientation explique mieux les mesures que la présentation normale.'} Le sens physique reste à vérifier.</p>${sample.orientation_matches?.length?`<h4>${uncertain?'Présentations à égalité':'Présentations expliquant le mieux les mesures'}</h4><div class='table-wrap'><table class='orientation-matches'><thead><tr><th>Longueur</th><th>Largeur</th><th>Hauteur</th><th>Écart cumulé</th></tr></thead><tbody>${sample.orientation_matches.map(match=>`<tr><td>${match.dimensions[2]} mm</td><td>${match.dimensions[0]} mm</td><td>${match.dimensions[1]} mm</td><td>${match.error_mm} mm</td></tr>`).join('')}</tbody></table></div><p class='muted'>Écart cumulé : somme des différences absolues entre les trois mesures et cette permutation BdD. Ce score ne certifie pas l’orientation physique.</p>`:''}</div>`;
  }
  const integer = value => Number(value||0).toLocaleString('fr-FR');
  function unknownCounter(unknown) {
    if(!unknown || !('total' in unknown))return '';
    const percent=100*(unknown.ratio||0),band=unknown.total?(percent<8?'is-good':percent<=12?'is-warning':'is-bad'):'';
    return `<button class='unknown-counter ${band}' data-unknown aria-label='Voir le détail des boîtes UNKNOWN'><span class='unknown-caption'>UNKNOWN · CB1 + CB2</span><span class='unknown-values'><strong>${integer(unknown.count)} <small>/ ${integer(unknown.total)}</small></strong><span class='unknown-percent'>${unknown.total?number(percent)+' %':'Indisponible'}</span></span></button>`;
  }
  function unknownHtml(unknown,state) {
    if(!unknown || !('total' in unknown))return '';
    return `<details class='section unknown-details' data-open='unknown' id='unknown-details'><summary>Boîtes finales UNKNOWN <span class='muted'>${integer(unknown.count)} / ${integer(unknown.total)} · ${unknown.total?number(100*unknown.ratio)+' %':'Indisponible'}</span></summary><p>Boîtes restées inconnues après les deux lecteurs CB1 et CB2, comptées une seule fois. Les inconnues temporaires identifiées ensuite sont exclues.</p><p>${unknown.alert?'Seuil de 7 % dépassé : vérifier la lecture des codes et les caméras.':unknown.total?'Seuil d’alerte : plus de 7 % des boîtes passées.':'Le nombre de boîtes passées est indisponible ; aucun taux ne peut être calculé.'}</p><div class='unknown-buckets'>${Object.entries(unknown.buckets||{}).map(([label,count])=>`<span>${esc(label)} <strong>${integer(count)}</strong></span>`).join('')}</div><div class='columns'><section><h3>Causes possibles</h3>${list(unknown.causes)}</section><section><h3>Contrôles conseillés</h3>${list(unknown.checks)}</section></div><h3>${unknown.count>10?'10 premières sur '+integer(unknown.count):integer(unknown.count)} boîtes UNKNOWN confirmées</h3>${(unknown.examples||[]).map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('')||'<p>Aucun exemple confirmé disponible.</p>'}</details>`;
  }
  function proofHtml(context,connected) {
    if(!context?.length)return 'Contexte indisponible.';
    return context.map(row=>`${row.navigation_id?`<button class='trace-line' data-source-navigate='${esc(row.navigation_id)}' ${connected?'':'disabled'} aria-label='Voir la ligne ${row.line} dans AlphaViewer'>L.${row.line}</button>`:`L.${row.line}`}  ${esc(row.text)}`).join('\n');
  }
  function seriesHtml(group,state) {
    return group.series.map((series,index)=>{
      const samples=group.examples.slice(series.example_start,series.example_start+series.example_count);
      const label=series.evidence_count>10?`10 premières sur ${integer(series.evidence_count)}`:`${integer(series.evidence_count)} occurrence(s)`;
      return `<details class='incident-series' data-open='series-${esc(group.id)}-${index}'><summary><strong>${integer(series.count)} ${series.distinct_events?'demandes distinctes':'occurrence(s)'}</strong><span>${esc(series.start_time_str)} → ${esc(series.end_time_str)} · ${esc(series.duration)}</span><span class='muted'>L.${series.first_line} à L.${series.last_line} · ${label}</span></summary><p>${esc(series.summary)}</p>${samples.map(sample=>sampleHtml({...sample,detail:structuredProof(group.code)?sample.detail:''},state.connected,'',state.tolerances)).join('')}</details>`;
    }).join('');
  }
  function sampleHtml(sample,connected,axis='',tolerances) {
    const measured=Array.isArray(sample.measured),complete=measured&&fullMeasurement(sample),orientation=sample.code==='ORIENTATION';
    const line=measured?sample.display_line:sample.line;
    const available=measured?complete:Boolean(line);
    const measures=measured?`<div class='table-wrap'><table class='box-measurements'><thead><tr><th>Dimension</th><th>BdD</th><th>Mesure Alpha</th>${orientation?'':'<th>Écart</th>'}</tr></thead><tbody>${[['Longueur',2,'length'],['Largeur',0,'width'],['Hauteur',1,'height']].map(([label,i,name])=>`<tr class='${name===axis?'selected-axis':''}'><td>${label}</td><td>${sample.expected[i]} mm</td><td>${sample.measured[i]} mm</td>${orientation?'':`<td class='${Math.abs(sample.deltas[i])>(sample.tolerances_mm?.[name]??tolerances?.[name]??3)?'measure-bad':'measure-good'}'>${signed(sample.deltas[i])} mm</td>`}</tr>`).join('')}</tbody></table></div>${orientation?orientationMatchesHtml(sample):`<p class='muted'>Écart positif : mesure au-dessus de la BdD. Écart négatif : mesure en dessous.</p>`}`:`<p>${esc(sample.detail)}</p>`;
    return `<article class='sample'><div class='sample-head'><div><strong>${esc(sample.display_time_str||sample.time_str)}</strong><p class='muted'>${esc([sample.box,sample.barcode].filter(Boolean).join(' · '))}</p></div><button class='small' data-navigate='${esc(sample.id)}' ${axis?`data-navigate-axis='${axis}'`:''} ${available?'':'data-missing-source'} ${connected&&available?'':'disabled'}>${measured?'Voir la boîte mesurée dans AlphaViewer':'Voir dans AlphaViewer'}</button></div>${measured?`<p class='sample-state'>${complete?'État après les trois mesures : longueur, largeur et hauteur.':'État complet indisponible : régénérer le rapport depuis la trace.'}${sample.final===false?' Mesure antérieure, hors effectif final.':''}${sample.invalid?' Mesure invalide, exclue du bilan.':''}</p>`:''}${sample.rejected_dimensions?`<p>Produit identifié puis rejeté pour dimensions : ${esc(sample.current_reference)}</p>`:''}${measures}<details class='sample-technical' data-open='proof-${esc(sample.id)}'><summary>Sources et contexte technique</summary>${line?`<p class='muted'>État affiché : L.${line}.</p>`:''}${sample.t4t?`<p>T4T (complément) : ${sample.t4t} mm ; diffT4 ${signed(sample.diff_t4)} mm.</p>`:''}${sample.sources?`<p>Sources : ${measured?`T4C L.${sample.sources.length} · C9 L.${sample.sources.width} · hauteur L.${sample.sources.height} · BdD L.${sample.sources.bdd} · identification L.${sample.sources.identity}`:Object.entries(sample.sources).map(([label,line])=>`${esc(label)} L.${line}`).join(' · ')}.</p>`:''}<pre>${proofHtml(sample.context,connected)}</pre></details></article>`;
  }
  function mount(root, data) {
    const groups = (data.groups || []).filter(group=>!data.orientation_references || group.code!=='ORIENTATION');
    const indexed = groups.map(group => ({group,search:JSON.stringify(group).toLocaleLowerCase('fr')}));
    const state = {search:'',family:'all',level:'all',pages:{},open:new Set(['measurements','camera']),connected:false,message:''};
    state.distributions=new Set();
    state.tolerances=data.measurements?.tolerances_mm;
    state.measurementSelection=null;
    state.orientations=Object.fromEntries(['probable','uncertain','flat_rotation','on_edge','other'].map(kind=>[kind,{page:0,barcode:''}]));
    state.measurementExamples=new Map((data.measurement_examples || []).map(sample=>[sample.id,sample]));
    const local = location.protocol==='http:' && location.hostname==='127.0.0.1' && /\/view\.html$/.test(location.pathname);
    const controller = new AbortController();
    let disposed = false, debounce;
    function render() {
      root.querySelectorAll('details[data-open]').forEach(node => node.open ? state.open.add(node.dataset.open) : state.open.delete(node.dataset.open));
      const filtered = indexed.filter(({group,search}) => (state.family==='all'||group.family===state.family) && (state.level==='all'||severity(group)===state.level) && (!state.search||search.includes(state.search.toLocaleLowerCase('fr')))).map(x => x.group);
      const counts = data.counts || {};
      const source = data.source || {};
      root.innerHTML = `<main class='report ${data.camera?.available?"has-sidebar":""}'><header class='hero'><div class='hero-top'><div class='hero-brand'><span class='brand-mark' aria-hidden='true'><svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.6'><path d='M4 18V6m4 12v-4m4 4V9m4 9V5m4 13v-7M3 21h18'/></svg></span><span class='eyebrow'>TraceAlphaViewer</span></div><p class='status' role='status'>${esc(state.message||(state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'Consultation autonome · navigation viewer indisponible.'))}</p></div><div class='hero-title'><h1>Rapport d’analyse Alpha</h1></div><div class='hero-footer'><div class='hero-meta'><div class='meta-item hero-file'><span>Trace analysée</span><strong class='source-name'>${esc(source.name||'Trace analysée')}</strong></div><div class='meta-item hero-period'><span>Période observée</span><strong>${esc(source.start)} → ${esc(source.end)}</strong></div><div class='meta-item hero-duration'><span>Durée</span><strong>${esc(source.duration)}</strong></div></div><button class='primary' data-pdf><svg aria-hidden='true' viewBox='0 0 24 24' width='20' height='20' fill='none' stroke='currentColor' stroke-width='1.7'><path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><path d='M14 2v6h6M12 11v7m-3-3 3 3 3-3'/></svg>Exporter PDF</button></div></header><div class='report-layout ${data.camera?.available?"has-camera":""}'><div class='report-content'><section class='section priorities'><div class='priority-heading'><div class='section-heading'><span class='eyebrow'>Synthèse terrain</span><h2>À vérifier en premier</h2><div class='priority-totals'><span><b>${counts.error||0}</b> problèmes critiques</span><span><b>${counts.warning||0}</b> alertes</span><span><b>${integer(counts.analyzed_boxes)}</b> boîtes observées</span></div></div>${unknownCounter(data.unknown)}</div>${data.unknown?.alert?`<button class='unknown-alert' data-unknown><strong>Lecture des codes à vérifier</strong><span>${integer(data.unknown.count)} UNKNOWN confirmées CB1+CB2 · ${number(100*data.unknown.ratio)} % des boîtes passées. Voir le détail →</span></button>`:''}<p class='priority-intro'>${esc(data.verdict?.text)}</p><div class='priority-grid'>${(data.priority||[]).slice(0,3).map((group,i)=>`<button data-priority='${esc(group.id)}'><span class='priority-number'>${i+1}</span><span class='badge ${severity(group)}'>${esc(severityLabel(group))}</span><strong>${esc(group.title)}</strong><span>${esc(group.field_explanation||group.impact)}</span><span class='priority-action'><b>Premier contrôle</b><br>${esc(action(group))}</span></button>`).join('')||'<p>Aucun problème prioritaire détecté.</p>'}</div></section>${unknownHtml(data.unknown,state)}<details class='section' data-open='measurements' ${state.open.has('measurements')?'open':''}><summary>Bilan des mesures de la trace <span class='muted'>Longueur · Largeur · Hauteur</span></summary>${measurementHtml(data.measurements,data,state)}</details>${orientationHtml(data,state)}<section class='diagnostic-list'><h2>Tous les diagnostics</h2><p class='muted'>Choisir un problème pour consulter ses contrôles et ses exemples. Les chiffres des mesures sont regroupés dans le bilan ci-dessus.</p><div class='filters'><input type='search' aria-label='Rechercher un diagnostic' placeholder='Rechercher un problème, une référence…' value='${esc(state.search)}'><select aria-label='Niveau' data-level>${[['all','Tous les niveaux'],['error','Critiques'],['warning','Alertes'],['info','Informations']].map(([key,label])=>`<option value='${key}' ${state.level===key?'selected':''}>${label}</option>`).join('')}</select><select aria-label='Famille' data-family>${(data.families||[]).filter(item=>item.id!=='critical').map(item=>`<option value='${item.id}' ${state.family===item.id?'selected':''}>${esc(item.label)}</option>`).join('')}</select></div><p id='problems' class='muted'>${filtered.length} type(s) de problème affichés sur ${groups.length}</p>${filtered.map(group=>groupHtml(group,state)).join('')||'<div class=empty>Aucun diagnostic pour ces critères.</div>'}</section><details class='section' data-open='zones' ${state.open.has('zones')?'open':''}><summary>Répartition par zone</summary>${list((data.zones||[]).map(zone=>`${zone.label||zone.family} : ${zone.occurrences} occurrences, ${zone.errors} critiques, ${zone.warnings} alertes`))}</details></div>${data.camera?.available?`<aside class='camera-sidebar' aria-label='Lecture des caméras'>${cameraHtml(data.camera,state.open.has('camera'))}</aside>`:''}</div><p class='footer'>Les constats proviennent de la trace. Les causes et pistes de réglage restent à confirmer sur la machine. Généré le ${esc(data.generated_at)}.</p></main>`;
      root.querySelectorAll('details[data-open]').forEach(node=>node.open=state.open.has(node.dataset.open));
      renderRobotAlert();
    }
    function renderRobotAlert() {
      const group=groups.find(item=>item.code==='DemVidageComplet');
      if(!criticalRobot(group))return;
      const metrics=group.metrics||{};
      const periods=['day'].filter(key=>metrics[key]?.count).map(key=>`Pic sur 24 h : ${metrics[key].count} (${metrics[key].start} → ${metrics[key].end})`).join(' · ');
      root.querySelector('.priority-intro')?.insertAdjacentHTML('beforebegin',`<button class='robot-drain-alert ${severity(group)}' data-priority='${esc(group.id)}'><strong>Vidage complet T5 demandé par le robot · ${esc(severityLabel(group))}</strong><span>${esc(group.summary)}</span><span>${esc(periods)}</span><span>Voir les demandes et les contrôles →</span></button>`);
    }
    function refreshStatus() {
      root.querySelectorAll('[data-navigate],[data-source-navigate]').forEach(button => button.disabled=!state.connected || button.hasAttribute('data-missing-source'));
      const label = root.querySelector('.status');
      if(label) label.textContent = state.message || (state.connected?'Liaison avec la trace ouverte dans AlphaViewer.':'La trace source est fermée ou la liaison est indisponible.');
    }
    async function status() {
      if(!local || disposed) return;
      try { const response=await fetch('status',{signal:controller.signal}); state.connected=response.ok && (await response.json()).connected; }
      catch { state.connected=false; }
      if(!disposed) refreshStatus();
    }
    async function navigateSample(id,axis) {
      const sample=state.measurementExamples.get(id);
      if(!id || ((axis || sample?.code==='ORIENTATION') && !fullMeasurement(sample||{}))) {
        state.message='État complet indisponible. Rouvrir la trace et régénérer le rapport pour afficher les trois mesures.';refreshStatus();return;
      }
      if(!local || !state.connected) {
        state.message='Le détail reste consultable ; la trace source est fermée ou la liaison avec AlphaViewer est indisponible.';refreshStatus();return;
      }
      state.message='Recherche de cet exemple dans AlphaViewer…';refreshStatus();
      try {
        const response=await fetch('navigate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sample_id:id,...(axis?{axis}:{})}),signal:controller.signal});
        const result=await response.json();
        state.message=result.ok?`AlphaViewer positionné à la ligne ${result.line}.`:(result.error || 'Navigation indisponible.');
      } catch {state.message='La trace source est fermée ou remplacée. Rouvrir le rapport depuis la bonne trace.';state.connected=false;}
      if(!disposed)refreshStatus();
    }
    async function click(event) {
      const button=event.target.closest('button'); if(!button) return;
      if(button.hasAttribute('data-pdf')) {downloadPdf(data);return;}
      if(button.hasAttribute('data-unknown')) {
        const detail=root.querySelector('#unknown-details');
        if(detail){detail.open=true;state.open.add('unknown');detail.scrollIntoView({behavior:'smooth',block:'start'});detail.querySelector('summary')?.focus({preventScroll:true});}return;
      }
      if(button.dataset.distributionAxis){const axis=button.dataset.distributionAxis;state.distributions.has(axis)?state.distributions.delete(axis):state.distributions.add(axis);render();root.querySelector(`[data-distribution-axis='${axis}']`)?.focus({preventScroll:true});return;}
      if(button.dataset.orientationBarcode){const kind=button.dataset.orientationKind,row=data.orientation_references?.[kind]?.find(row=>row.barcode===button.dataset.orientationBarcode);state.orientations[kind]={page:0,barcode:button.dataset.orientationBarcode};const detail=root.querySelector(`[data-open="orientation-${kind}"]`);if(detail)detail.open=true;render();root.querySelector(`[data-orientation-list='${kind}']`)?.scrollIntoView({block:'start'});await navigateSample(row?.navigation_sample_id);return;}
      if(button.hasAttribute('data-orientation-back')){state.orientations[button.dataset.orientationKind]={page:0,barcode:''};render();return;}
      if(button.hasAttribute('data-orientation-page')){state.orientations[button.dataset.orientationKind].page=Number(button.dataset.orientationPage);render();return;}
      if(button.dataset.measureAxis){state.measurementSelection={axis:button.dataset.measureAxis,side:button.dataset.measureSide,page:0,barcode:''};render();root.querySelector('.measurement-reference-list')?.scrollIntoView({block:'nearest'});return;}
      if(button.hasAttribute('data-measure-close')){state.measurementSelection=null;render();return;}
      if(button.hasAttribute('data-measure-back')){state.measurementSelection.barcode='';state.measurementSelection.page=0;render();return;}
      if(button.dataset.measureBarcode){
        const {axis,side}=state.measurementSelection;
        const row=data.measurement_references?.[axis]?.[side]?.find(item=>item.barcode===button.dataset.measureBarcode);
        state.measurementSelection.barcode=button.dataset.measureBarcode;state.measurementSelection.page=0;render();
        if(side==='under'||side==='over')await navigateSample(row?.navigation_sample_id,axis);
        return;
      }
      if(button.hasAttribute('data-measure-rare-page')){state.measurementSelection.rarePage=Number(button.dataset.measureRarePage);render();return;}
      if(button.hasAttribute('data-measure-page')){state.measurementSelection.page=Number(button.dataset.measurePage);render();return;}
      if(button.dataset.navigate) {
        await navigateSample(button.dataset.navigate,button.dataset.navigateAxis);
        return;
      }
      if(button.dataset.sourceNavigate){await navigateSample(button.dataset.sourceNavigate);return;}
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
  function orientationRowsHtml(data,state,kind) {
    const rows=data.orientation_references?.[kind]||[],selection=state.orientations[kind];
    const row=rows.find(row=>row.barcode===selection.barcode);
    const items=selection.barcode?(row?.sample_ids||[]).map(id=>state.measurementExamples.get(id)).filter(Boolean):rows;
    const visible=items.slice(selection.page*25,(selection.page+1)*25);
    const content=selection.barcode?`<div class='product-heading'><div><h3>${esc(row?.name||'Produit identifié')}</h3><p>Référence ${esc(selection.barcode)} · ${row?.count}/${row?.total} boîtes exploitables de ce produit (${number(row?.percent)} %).</p></div><button data-orientation-back data-orientation-kind='${kind}'>Retour aux références</button></div><div class='orientation-proofs'>${visible.map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('')}</div>`:`<div class='table-wrap'><table><thead><tr><th>Produit / référence</th><th>Boîtes concernées</th><th>Part de ce produit</th></tr></thead><tbody>${visible.map(row=>`<tr><td><strong>${esc(row.name||'Produit identifié')}</strong><br><button class='reference-link' data-orientation-kind='${kind}' data-orientation-barcode='${esc(row.barcode)}'>${esc(row.barcode)}</button>${row.variant_count>1?'<p class=variant-note>Plusieurs variantes BdD ; comparaison propre à chaque boîte.</p>':''}</td><td>${row.count} sur ${row.total}</td><td>${number(row.percent)} %</td></tr>`).join('')}</tbody></table></div>`;
    if(!items.length)return '<p>Aucune boîte concernée avec les trois sources de mesure disponibles.</p>';
    return content+`<div class='pagination'><button class='small' data-orientation-kind='${kind}' data-orientation-page='${selection.page-1}' ${selection.page===0?'disabled':''}>Précédents</button><span>Page ${selection.page+1}/${Math.ceil(items.length/25)} · ${items.length} ${selection.barcode?'boîtes':'produits'}</span><button class='small' data-orientation-kind='${kind}' data-orientation-page='${selection.page+1}' ${(selection.page+1)*25>=items.length?'disabled':''}>Suivants</button></div>`;
  }
  function orientationHtml(data,state) {
    if(!data.orientation_references)return '';
    const probable=data.orientation_references.probable||[],uncertain=data.orientation_references.uncertain||[];
    const count=rows=>rows.reduce((sum,row)=>sum+row.count,0);
    const categories=data.orientation_categories||[];
    const preview=categories.flatMap(category=>(data.orientation_references[category.id]||[]).map(row=>({...row,category}))).sort((a,b)=>b.count-a.count||b.percent-a.percent||a.barcode.localeCompare(b.barcode)).slice(0,3);
    const categorized=categories.length?`<div class='orientation-preview'><h3>Références les plus concernées</h3>${preview.map(row=>`<p><button class='reference-link' data-orientation-kind='${row.category.id}' data-orientation-barcode='${esc(row.barcode)}'>${esc(row.name||row.barcode)}</button> · ${row.count}/${row.total} boîtes (${number(row.percent)} %) <span class='orientation-tag'>${esc(row.category.label)}</span></p>`).join('')||'<p>Aucune orientation probable.</p>'}</div>${categories.map(category=>{const rows=data.orientation_references[category.id]||[];return `<details class='orientation-category' data-orientation-category='${category.id}' data-open='orientation-${category.id}'><summary><strong>${esc(category.label)}</strong><span>${count(rows)} boîtes · ${rows.length} références</span></summary><p>${esc(category.hypothesis)}</p><div class='orientation-checks'><strong>Contrôles conseillés</strong>${list(category.checks)}</div><div data-orientation-list='${category.id}'>${orientationRowsHtml(data,state,category.id)}</div></details>`;}).join('')}`:'';
    return `<section class='section orientations'><h2>Boîtes dans le mauvais sens</h2><p><strong>Orientation probable d’après les dimensions</strong> · ${count(probable)} boîtes, ${probable.length} produits distincts.</p><p class='muted'>Une permutation des dimensions BdD explique mieux les trois mesures. Le sens physique reste à vérifier. Toutes les références sont affichées, même pour un cas rare ; ces boîtes restent exclues des défauts de mesure.</p><p class='muted'>Chaque proportion porte sur les cycles exploitables de ce produit avant exclusion des orientations. Cliquer sur une référence rejoint sa première boîte concernée après les trois mesures.</p>${categorized||`<div data-orientation-list='probable'>${orientationRowsHtml(data,state,'probable')}</div>`}<details class='orientation-uncertain' data-open='orientation-uncertain'><summary>Orientations indécidables · ${count(uncertain)} boîtes, ${uncertain.length} produits distincts</summary><p>Le sens normal et une autre orientation obtiennent le même score. Ces cas sont exclus du bilan de mesure, sans être classés comme des boîtes dans le mauvais sens.</p><div data-orientation-list='uncertain'>${orientationRowsHtml(data,state,'uncertain')}</div></details></section>`;
  }
  function cameraHtml(camera, open=true) {
    if(!camera?.available)return '';
    const max=Math.max(1,...(camera.chart||[]).map(row=>row.success_count));
    return `<details class='section camera-panel' data-open='camera' ${open?'open':''}><summary>Lecture des caméras</summary><p class='muted camera-note'>${esc(camera.note)}</p>${(camera.chart||[]).map(row=>`<div class='camera-row'><div class='camera-row-heading'><span>${esc(row.label)}</span><strong>${row.success_count} lectures</strong></div><div class='bar'><i class='${row.status==='zero'?'zero':''}' style='width:${100*row.success_count/max}%'></i></div><p class='muted'>${esc(row.status_label)}</p></div>`).join('')}<div class='camera-readers'>${(camera.reader_stats||[]).map(row=>`<section><strong>${esc(row.reader)} · ${row.boxes} boîtes</strong><p>${esc(row.zero_code_label)} lectures à 0 code</p><small>Caméras attendues : ${esc(row.expected_cameras)}</small></section>`).join('')}</div></details>`;
  }
  function robotDaysHtml(group,state) {
    const metrics=group.metrics||{},days=group.daily||metrics.daily||[];
    const total=group.occurrence_count??metrics.total??0,trace=metrics.trace||{};
    const summary=trace.available?`${total} demandes sur ${trace.days} jours de trace`:`${total} demandes · dates indisponibles`;
    return `<div class='robot-days'><p class='robot-total'>${esc(summary)}</p><p class='muted'>${esc(group.trace_period||(trace.available?`Trace analysée du ${trace.start} au ${trace.end}`:'Les dates calendaires ne sont pas disponibles dans ce rapport.'))}</p>${metrics.requests_start?`<p>Demandes du ${esc(metrics.requests_start)} au ${esc(metrics.requests_end)}</p>`:''}${days.length?days.map((day,index)=>day.count?`<details class='robot-day' data-open='robot-day-${esc(group.id)}-${index}'><summary><strong>${esc(day.label)}</strong><span>${day.count} demande(s)</span></summary><p class='muted'>De ${esc(day.first_time)} à ${esc(day.last_time)} · ${day.example_count??day.examples?.length??0} premières preuves sur ${day.count}</p>${(day.examples||(group.examples||[]).slice(day.example_start,day.example_start+day.example_count)).map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('')}</details>`:`<p class='robot-zero-day'>${esc(day.label)}<span>Aucune demande</span></p>`).join(''):seriesHtml(group,state)}</div>`;
  }
  function groupHtml(group,state) {
    const examples=group.examples||[],page=state.pages[group.id];
    const selected=page==null?examples.filter(s=>(group.representative_ids||[]).includes(s.id)):examples.slice(page*25,page*25+25);
    const pagination=examples.length>3?`<div class="pagination">${page==null?`<button data-page-group="${esc(group.id)}" data-page="0">Voir les ${examples.length} exemples</button>`:`<button data-page-group="${esc(group.id)}" data-page="${Math.max(0,page-1)}" ${page===0?'disabled':''}>Précédents</button><span>Page ${page+1} / ${Math.ceil(examples.length/25)}</span><button data-page-group="${esc(group.id)}" data-page="${page+1}" ${(page+1)*25>=examples.length?'disabled':''}>Suivants</button>`}</div>`:'';
    return `<details class="group ${severity(group)}" data-group="${esc(group.id)}" data-open="${esc(group.id)}" ${state.open.has(group.id)?'open':''}><summary><div><div class="badges"><span class="badge ${severity(group)}">${severityLabel(group)}</span><span class="badge">${esc(group.field_zone_label || group.family_label)}</span><span class="badge">${esc(group.code)}</span></div><h3>${esc(group.title)}</h3><p class="plain-explanation">${esc(group.field_explanation || group.impact || group.symptom)}</p><p>${esc(group.affected_label || group.metric)} · ${esc(action(group))}</p><p class="muted">${esc(group.evidence)}</p>${groupRecurrenceHtml(group)}</div></summary><div class="group-body"><section><h3>Constat et chiffres</h3><p>${esc(group.field_explanation || group.field_impact || group.impact)}</p><p>${esc(group.symptom)}</p>${list(group.business_lines)}<p class="muted">${group.incident_count} diagnostics · Confiance : ${esc(group.confidence)}</p>${Object.keys(group.measurement_stats || {}).length?'<p class="muted">Les compteurs, plages et pistes de mesure figurent dans le bilan en haut du rapport.</p>':''}</section><div class="columns"><section><h3>Causes possibles</h3>${list(group.probable_causes)}</section><section><h3>Contrôles conseillés</h3>${list(group.checks)}</section></div><section class="evidence"><h3>Exemples réels <span class="muted">${group.series?group.series.reduce((total,series)=>total+series.evidence_count,0):examples.length} occurrence(s) · ${examples.length} preuve(s) préparée(s)</span></h3>${group.code==='DemVidageComplet'?robotDaysHtml(group,state):group.series?seriesHtml(group,state):selected.map(sample=>sampleHtml(sample,state.connected,'',state.tolerances)).join('') || '<p class="muted">Aucun exemple individuel disponible.</p>'}${group.series?'':pagination}</section><details><summary>Détail complet des diagnostics regroupés</summary>${(group.incidents||[]).map(item=>`<article class="sample"><strong>${esc(item.start_time_str)} → ${esc(item.end_time_str)} · L.${item.first_line} à L.${item.last_line}</strong><p>${esc(item.title)} · ${item.count} occurrence(s) · ${esc(item.duration)}</p><p>${esc(item.summary)}</p><p>${esc(item.symptom)}</p><p class="muted">Confiance : ${esc(item.confidence)}</p>${list(item.probable_causes)}${list(item.checks)}</article>`).join('')}</details></div></details>`;
  }
  function pdfLines(data) {
    const result=[],add=(text,kind='text')=>result.push({text:String(text??''),kind});
    const table=(headers,rows)=>result.push({kind:'table',headers,rows});
    add(data.source?.name||'Trace analysée','title');
    add(`${data.source?.start||''} → ${data.source?.end||''} · ${data.source?.duration||''} · Généré le ${data.generated_at}`);
    if(data.unknown && 'total' in data.unknown){
      const unknown=data.unknown;
      add(`UNKNOWN CB1+CB2 : ${unknown.count} / ${unknown.total} boîtes · ${unknown.total?number(100*unknown.ratio)+' %':'Indisponible'}`,'metric');
      if(unknown.alert)add('Seuil de 7 % dépassé : vérifier les caméras et la lecture des codes.','group');
    }
    const robot=(data.groups||[]).find(group=>group.code==='DemVidageComplet');
    function robotDetails(robot){
      const trace=robot.metrics?.trace;
      add(trace?.available?`${robot.occurrence_count} demandes sur ${trace.days} jours de trace`:'Dates calendaires indisponibles');
      if(robot.trace_period)add(robot.trace_period);
      if(robot.metrics?.requests_start)add(`Demandes du ${robot.metrics.requests_start} au ${robot.metrics.requests_end}`);
      for(const day of robot.daily||robot.metrics?.daily||[]){
        add(`${day.label} : ${day.count?day.count+' demande(s)':'Aucune demande'}`,'metric');
        for(const sample of day.examples||(robot.examples||[]).slice(day.example_start,day.example_start+day.example_count))add(`${sample.display_time_str||sample.time_str} · L.${sample.line}`);
      }
      for(const [name,label] of [['day','24 h']]){
        const period=robot.metrics?.[name];
        if(period)add(`Pic sur ${label} : ${period.count} · ${period.start} → ${period.end}`);
      }
    }
    if(criticalRobot(robot)){
      add(`Vidage complet T5 demandé par le robot · ${severityLabel(robot)}`,'section');add(robot.summary,'metric');
      robotDetails(robot);
    }
    add('À vérifier en premier','section');add(data.verdict?.text);
    for(const group of (data.priority||[]).slice(0,3)){add(`[${severityLabel(group)}] ${group.title}`,'group');add(group.field_explanation||group.impact);add('Premier contrôle : '+action(group));}
    add('Bilan des mesures de la trace','section');add(globalMeasurementText(data.measurements||{}),'metric');add(measurementTotal(data.measurements||{}));
    add(thresholdText(data.measurements));
    add('Écart = mesure Alpha - BdD. Reconnaissance CB1/CB2 requise ; orientations probables ou indécidables exclues.');
    const axes=['length','width','height'].filter(name=>data.measurements?.axes?.[name]);
    add('Les écarts marquants ci-dessous concernent les produits ayant au moins 10 % de défauts du côté choisi. Les cas rares restent inclus dans tous les totaux.');
    table(['Dimension','Boîtes défaut/total','Écart marquant en moins','Écart marquant en trop'],axes.map(name=>{const axis=data.measurements.axes[name];return [axisInfo[name].label,axis.all.count?`${axis.anomalies.count}/${axis.all.count}`:'Aucune comparable',displayExtreme(data,name,'under'),displayExtreme(data,name,'over')];}));
    for(const name of axes){
      const axis=data.measurements.axes[name],bad=axis.anomalies,all=axis.all,info=axisInfo[name];
      add(`${info.label} · ${info.source}`,'group');add(`À vérifier : écart > ${axisTolerance(data.measurements,name)} mm en valeur absolue.`);
      add(measurementCounts(axis),'metric');
      add(`${info.under} : ${bad.under_count} ; ${info.over} : ${bad.over_count}. ${bad.references} produits concernés sur ${all.references} produits distincts comparables.`);
      for(const text of recurrenceBrief(axis))add(text);
      add('Répartition de toutes les mesures comparables','metric');add('Les mesures conformes sont incluses. Chaque boîte est comptée une fois.');
      table(['Écart signé','Boîtes','Part des comparables'],(axis.frequencies||[]).map(row=>[`${signed(row.delta)} mm`,String(row.count),`${number(row.percent)} %`]));
      for(const side of ['under','over']){
        const rows=primaryRows(data,name,side),rare=(data.measurement_references?.[name]?.[side]||[]).filter(row=>!isPrimary(row));
        if(!rows.length)add(`${info[side]} : aucun produit n’atteint 10 %.`);
        if(rare.length)add(`${rare.length} produits dans les cas rares (< 10 %), consultables dans le rapport web.`);
        if(rows.length)add(`${info[side]} : ${rows.length} produits ; les 3 plus grands écarts`,'metric');
        for(const row of rows.slice(0,3))add(`${row.name||'Produit identifié'} · ${row.barcode} : ${row.count}/${row.total} boîtes ; pire écart ${signed(row.worst)} mm.`);
      }
    }
    if(data.orientation_references){
      add('Boîtes dans le mauvais sens','section');add('Orientation probable d’après les dimensions. Le sens physique reste à vérifier. Toutes les références sont affichées, sans filtre de 10 %.');
      add('Les proportions portent sur les cycles exploitables du produit avant exclusion pour orientation. Ces boîtes restent exclues des défauts de mesure.');
      const orientationKinds=data.orientation_categories?.length?[...data.orientation_categories.map(category=>category.id),'uncertain']:['probable','uncertain'];
      for(const kind of orientationKinds){
        const rows=data.orientation_references[kind]||[];
        const category=data.orientation_categories?.find(category=>category.id===kind);
        add(category?.label||(kind==='probable'?'Orientations probables':'Orientations indécidables'),'group');
        if(category){add(category.hypothesis);for(const check of category.checks||[])add('À vérifier : '+check);}
        if(kind==='uncertain')add('Une autre orientation et le sens normal obtiennent le même score ; ces cas ne sont pas classés comme des boîtes dans le mauvais sens.');
        add(`${rows.reduce((sum,row)=>sum+row.count,0)} boîtes, ${rows.length} produits distincts.`);
        if(rows.length)table(['Produit','Référence','Boîtes / exploitables','Part du produit'],rows.map(row=>[row.name||'Produit identifié',row.barcode,`${row.count}/${row.total}`,`${number(row.percent)} %`]));
        for(const row of rows.slice(0,3)){
          const sample=(data.measurement_examples||[]).find(sample=>sample.id===row.navigation_sample_id);if(!sample)continue;
          add(`${sample.display_time_str||sample.time_str} · ${sample.name||''} · ${sample.barcode} · ${sample.box}`,'example');
          table(['Dimension','BdD','Mesure Alpha'],[['Longueur',2],['Largeur',0],['Hauteur',1]].map(([label,index])=>[label,`${sample.expected[index]} mm`,`${sample.measured[index]} mm`]));
          if(sample.orientation_matches?.length){add(kind==='uncertain'?'Présentations à égalité':'Présentations expliquant le mieux les mesures','metric');table(['Longueur','Largeur','Hauteur','Écart cumulé'],sample.orientation_matches.map(match=>[`${match.dimensions[2]} mm`,`${match.dimensions[0]} mm`,`${match.dimensions[1]} mm`,`${match.error_mm} mm`]));}
        }
      }
      add('Les autres boîtes et leurs lignes sources sont consultables dans le détail web de chaque produit.');
    }
    add('Boîtes non comparées','section');
    const excluded=Object.entries(data.measurements?.excluded||{}).filter(([,count])=>count);
    if(excluded.length)for(const [key,count] of excluded)add(`${count} · ${exclusionLabels[key]||key}`);
    else add('Aucune boîte exclue.');
    add('Ces boîtes ne sont comptées ni conformes ni hors tolérance.');
    if(data.camera?.available){add('Lecture des caméras','section');add(data.camera.note);for(const row of data.camera.chart||[])add(`${row.label} : ${row.success_count} lectures réussies · ${row.status_label}`);for(const row of data.camera.reader_stats||[])add(`${row.reader} : ${row.zero_code_label} lectures à 0 code ; caméras ${row.expected_cameras}`);}
    const measurementExamples=new Map((data.measurement_examples||[]).map(sample=>[sample.id,sample]));
    const representatives=new Map();
    for(const name of axes){
      const index={length:2,width:0,height:1}[name];
      const candidates=['under','over'].map(side=>primaryRows(data,name,side)[0]?.sample_ids?.[0]).map(id=>measurementExamples.get(id)).filter(Boolean);
      candidates.sort((a,b)=>Math.abs(b.deltas[index])-Math.abs(a.deltas[index])||a.display_line-b.display_line);
      if(candidates[0])representatives.set(candidates[0].id,candidates[0]);
    }
    if(representatives.size){add('Exemples de boîtes mesurées','section');for(const sample of representatives.values()){
      add(`${sample.display_time_str||sample.time_str} · ${sample.name||''} · ${sample.barcode} · ${sample.box}`,'example');
      table(['Dimension','BdD','Mesure Alpha','Écart'],[['Longueur T4C',2],['Largeur',0],['Hauteur',1]].map(([label,i])=>[label,`${sample.expected[i]} mm`,`${sample.measured[i]} mm`,`${signed(sample.deltas[i])} mm`]));
      if(sample.t4t)add(`T4T (complément) : ${sample.t4t} mm ; diffT4 ${signed(sample.diff_t4)} mm.`);
    }}
    add('Diagnostics et contrôles','section');
    for(const group of data.groups||[]){
      if(['T4_LENGTH','T5_WIDTH','T5_HEIGHT','GLOBAL'].includes(group.code)||(data.orientation_references&&group.code==='ORIENTATION'))continue;
      add(`[${severityLabel(group)}] ${group.title}`,'group');add(group.affected_label||group.metric);
      add(group.field_explanation||group.impact);add('Premier contrôle : '+action(group));
      if(structuredProof(group.code))for(const line of group.business_lines||[])add(line);
      if(group.code==='DemVidageComplet'&&!criticalRobot(group))robotDetails(group);
      for(const check of (group.checks||[]).filter(check=>check!==action(group)).slice(0,2))add('À vérifier : '+check);
      const examples=(group.examples||[]).filter(sample=>(group.representative_ids||[]).includes(sample.id)).slice(0,3);
      for(const sample of examples){
        add(`${sample.display_time_str||sample.time_str} · ${sample.box||''} · ${sample.barcode||''}`,'example');
        if(sample.measured){table(['Dimension','BdD','Mesure Alpha','Écart'],[['Longueur T4C',2],['Largeur',0],['Hauteur',1]].map(([label,i])=>[label,`${sample.expected[i]} mm`,`${sample.measured[i]} mm`,`${signed(sample.deltas[i])} mm`]));if(sample.t4t)add(`T4T (complément) : ${sample.t4t} mm ; diffT4 ${signed(sample.diff_t4)} mm.`);}
        else add(sample.detail);
        if(structuredProof(group.code))add(`Sources : ${Object.entries(sample.sources||{}).map(([label,line])=>`${label} L.${line}`).join(' · ')}.`);
      }
    }
    add('Statistiques et explications des mesures','section');
    add('Les extrêmes bruts et toutes les mesures, y compris les cas rares, restent inclus dans ces statistiques.');
    add('Les écarts en moins et en trop se compensent dans le décalage moyen. L’erreur moyenne est leur amplitude sans signe. Ces moyennes ne déterminent pas une correction de réglage. Les références comptent des produits distincts, pas des boîtes.');
    for(const name of axes){
      const axis=data.measurements.axes[name];add(axisInfo[name].label,'group');
      for(const [label,stats] of [['Mauvaises mesures',axis.anomalies],['Toutes les comparables',axis.all]]){
        if(!stats.count){add(`${label} : aucune.`);continue;}
        add(`${label} : ${stats.count} boîtes, ${stats.references} produits ; plage ${range(stats)}.`);
        add(`Décalage moyen ${signed(stats.mean_signed)} mm ; erreur moyenne ${number(stats.mean_abs)} mm. Erreur absolue : min ${number(stats.min_abs)}, max ${number(stats.max_abs)} mm.`);
      }
      add('Comment les répétitions sont calculées','metric');
      for(const side of ['under','over']){
        const item=axis.recurrence?.[side],cluster=item?.cluster;if(!cluster)continue;
        const label=side==='under'?'En moins':'En trop';
        add(`${label} : ${item.frequencies.slice(0,5).map(row=>`${row.count} boîtes à ${signed(row.delta)} mm`).join(' ; ')}.`);
        add(`Autour de ${signed(cluster.center)} mm (+/-1 mm) : ${cluster.bad_count} défauts et ${cluster.good_count} mesures conformes voisines ; ${cluster.count} mesures sur ${cluster.references} produits. Plage ${signed(cluster.min_signed)} à ${signed(cluster.max_signed)} mm.`);
        add(`Ces défauts représentent ${number(cluster.percent_side)} % des défauts de ce côté, ${number(cluster.percent_bad)} % de toutes les mauvaises mesures et ${number(cluster.bad_percent_all)} % des comparables. Le groupe entier représente ${number(cluster.percent_all)} % des comparables.`);
        add((cluster.repeated_references?`Répétition observée sur ${cluster.repeated_references} produit(s) mesurés plusieurs fois.`:'Répétition par produit non confirmée.')+(cluster.limited?' Effectif limité.':''));
        if(cluster.dominant)add(`Produit le plus représenté : ${cluster.dominant.barcode}, ${cluster.dominant.count}/${cluster.count} mesures (${number(cluster.dominant.percent)} %).`);
        if(cluster.advice)add('Piste à confirmer : '+cluster.advice);
      }
      if(axis.bias&&!hasRepeatedOffsets(axis))add(biasText(axis.bias));
      for(const text of axis.interpretation||[])add('Piste à confirmer : '+text);
      const products=new Map();
      for(const side of ['under','over'])for(const row of primaryRows(data,name,side).slice(0,3))products.set(`${side}:${row.barcode}`,{...row,side});
      for(const row of products.values()){add(`${axisInfo[name][row.side]} · ${row.name||''} · ${row.barcode}`,'example');if(row.variant_count>1)add('Plusieurs variantes BdD : observations séparées.');for(const observation of (row.observations||[]).slice(0,3))add(observationText(observation));}
    }
    add('Les sources techniques et tous les exemples restent accessibles dans le rapport web. Les pistes proposées demandent une vérification sur la machine.');
    return result;
  }
  /* PDF vectoriel autonome : accents WinAnsi, retours et fonds dimensionnes. */
  function buildPdf(data) {
    const encode=text=>String(text).replace(/→/g,'->').replace(/[−–—]/g,'-').replace(/’/g,"'").replace(/œ/g,'oe').replace(/[^\x20-\x7e\xa0-\xff]/g,' ');
    const escape=text=>encode(text).replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)');
    const text=(value,x,y,size,bold=false)=>`BT /${bold?'F2':'F1'} ${size} Tf ${x} ${y} Td (${escape(value)}) Tj ET\n`;
    const wrap=(value,max)=>{const words=encode(value).split(/\s+/);const lines=[];let line='';for(let word of words){while(word.length>max){if(line){lines.push(line);line='';}lines.push(word.slice(0,max));word=word.slice(max);}if((line+' '+word).trim().length>max){lines.push(line);line=word;}else line=(line+' '+word).trim();}if(line)lines.push(line);return lines.length?lines:[''];};
    const pages=[];let body='',y=745;
    const header=()=>{body+='q 0.92 0.96 1 rg 36 778 523 42 re f Q\nq 0.09 0.23 0.36 rg\n'+text('Rapport d’analyse Alpha · TraceAlphaViewer',48,794,15,true)+'Q\n';};
    const finish=()=>{body+=text(`TraceAlphaViewer | page ${pages.length+1}`,42,28,8);pages.push(body);body='';y=745;header();};header();
    const items=pdfLines(data);
    for(let index=0;index<items.length;index++) {
      const item=items[index];
      if(item.kind==='table'){
        const widths=item.headers.length===3?[180,120,180]:[142,108,108,122],xs=item.headers.length===3?[48,228,348]:[48,190,298,406],size=9,gap=14;
        const rowLines=row=>row.map((cell,i)=>wrap(cell,Math.floor((widths[i]-12)/(size*.55))));
        const drawRow=(row,bold)=>{
          const cells=rowLines(row),height=Math.max(...cells.map(lines=>lines.length))*gap+12;
          if(y-height<55){finish();if(!bold)drawRow(item.headers,true);}
          if(bold)body+=`q 0.88 0.93 0.98 rg 38 ${y-height+3} 519 ${height} re f Q\n`;
          else body+=`q 0.86 0.89 0.93 RG 38 ${y-height+3} m 557 ${y-height+3} l S Q\n`;
          cells.forEach((lines,i)=>lines.forEach((line,j)=>{body+=text(line,xs[i],y-15-j*gap,size,bold);}));y-=height;
        };
        const height=item.rows.reduce((total,row)=>total+Math.max(...rowLines(row).map(lines=>lines.length))*gap+12,30);
        if(y-Math.min(height,56)<55)finish();
        drawRow(item.headers,true);for(const row of item.rows)drawRow(row,false);y-=14;continue;
      }
      const size=item.kind==='title'?16:item.kind==='section'?13:item.kind==='group'?11:10;
      const bold=item.kind!=='text';const lines=wrap(item.text,Math.floor(480/(size*.55)));
      const gap=size+5;const height=lines.length*gap+10;
      const next=items[index+1];
      const tableHeight=next?.kind==='table'?next.rows.reduce((total,row)=>total+Math.max(...row.map((cell,i)=>wrap(cell,Math.floor(((next.headers.length===3?[180,120,180]:[142,108,108,122])[i]-12)/(9*.55))).length))*14+12,44):0;
      const reserve=['section','group','metric','example'].includes(item.kind)?Math.max(42,Math.min(tableHeight,150)):0;
      if(y-height-reserve<55 && height<680)finish();
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
