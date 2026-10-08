'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const emptyData = {
  generated_at: '-',
  counts: { error: 0, warning: 0, info: 0, incidents: 0, types: 0 },
  verdict: {
    level: 'ok',
    label: 'Rien de bloquant',
    title: 'Aucun rapport charge',
    text: 'Les donnees du rapport ne sont pas disponibles.',
  },
  groups: [],
  priority: [],
  zones: [],
  camera: { available: false, chart: [], reader_stats: [], alerts: [], note: '' },
  families: [],
};

const severityStyles = {
  error: 'border-red-700 bg-red-50 text-red-950',
  warning: 'border-amber-600 bg-amber-50 text-amber-950',
  info: 'border-blue-600 bg-blue-50 text-blue-950',
};

const verdictStyles = {
  critical: 'border-red-700 bg-red-50',
  warning: 'border-amber-600 bg-amber-50',
  ok: 'border-emerald-700 bg-emerald-50',
};

const cameraColors = {
  CB1: '#2e7d55',
  CB2: '#2563a7',
};

function Badge({ children, className = '' }) {
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-1 text-xs font-bold ${className}`}>
      {children}
    </span>
  );
}

function SeverityBadge({ severity, label }) {
  return (
    <Badge className={severityStyles[severity] || 'border-slate-300 bg-slate-50 text-slate-800'}>
      {label || severity}
    </Badge>
  );
}

function fieldSeverity(group) {
  return group.field_severity || group.severity || 'info';
}

function fieldSeverityLabel(group) {
  return group.field_severity_label || group.severity_label || fieldSeverity(group);
}

function fieldAction(group) {
  return group.field_action || group.action || group.title || '-';
}

function fieldImpact(group) {
  return group.field_impact || group.impact || '-';
}

function fieldZone(group) {
  return group.field_zone_label || group.family_label || '-';
}

function StatCard({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-3xl font-black leading-none text-slate-950">{value}</div>
      <div className="mt-1 text-sm text-slate-500">{label}</div>
    </div>
  );
}

function PriorityTable({ groups }) {
  const rows = groups || [];
  if (!rows.length) {
    return <p className="p-4 text-sm text-slate-500">Aucun incident detecte.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-left text-sm">
        <thead className="bg-slate-100 text-xs uppercase text-slate-600">
          <tr>
            <th className="whitespace-nowrap px-3 py-2">Priorite</th>
            <th className="whitespace-nowrap px-3 py-2">Zone</th>
            <th className="min-w-[230px] px-3 py-2">Probleme</th>
            <th className="whitespace-nowrap px-3 py-2">Volume</th>
            <th className="min-w-[260px] px-3 py-2">Impact</th>
            <th className="min-w-[260px] px-3 py-2">Action</th>
            <th className="whitespace-nowrap px-3 py-2">Lignes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((group, index) => (
            <tr key={`${group.code}-${group.first_line}-${index}`} className="border-t border-slate-200 align-top">
              <td className="px-3 py-3">
                <SeverityBadge severity={fieldSeverity(group)} label={fieldSeverityLabel(group)} />
              </td>
              <td className="px-3 py-3 font-black text-slate-900">{fieldZone(group)}</td>
              <td className="px-3 py-3">
                <div className="font-black">{group.field_explanation || fieldAction(group)}</div>
                <div className="mt-1 text-xs text-slate-500">{group.belt} / {group.code}</div>
              </td>
              <td className="whitespace-nowrap px-3 py-3 font-black text-blue-950">{group.affected_label || group.metric}</td>
              <td className="px-3 py-3 text-slate-700">{fieldImpact(group)}</td>
              <td className="px-3 py-3 font-bold text-slate-800">{fieldAction(group)}</td>
              <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-500">
                L.{group.first_line} -&gt; L.{group.last_line}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ZoneCard({ zone }) {
  return (
    <article className="border-t border-slate-200 py-3 first:border-t-0">
      <div className="flex items-center justify-between gap-3 font-black">
        <span>{zone.label}</span>
        <span>{zone.groups} type(s)</span>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {zone.occurrences} occurrence(s), {zone.errors} critique(s), {zone.warnings} alerte(s)
      </p>
      <p className="mt-2 text-sm">{zone.top_action || 'Controle terrain recommande'}</p>
    </article>
  );
}

function CameraPanel({ camera }) {
  if (!camera?.available) {
    return (
      <section id="camera-section" className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-black">Performance des cameras</h2>
        <p className="mt-2 text-sm text-slate-500">Donnees cameras indisponibles pour ce rapport.</p>
      </section>
    );
  }

  const chart = camera.chart || [];
  const maxCount = Math.max(1, ...chart.map((item) => Number(item.success_count || 0)));

  return (
    <section id="camera-section" className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-black uppercase tracking-wide text-slate-500">Lecture cameras</div>
          <h2 className="text-lg font-black">Performance des cameras</h2>
        </div>
        <p className="text-sm text-slate-500">Classement de celle qui lit le plus a celle qui lit le moins.</p>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chart} layout="vertical" margin={{ top: 8, right: 30, bottom: 8, left: 28 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" domain={[0, maxCount]} allowDecimals={false} />
              <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => [`${value} lecture(s)`, 'Reussites']} />
              <Bar dataKey="success_count" radius={[0, 5, 5, 0]}>
                {chart.map((entry) => (
                  <Cell
                    key={`${entry.reader}-${entry.camera}`}
                    fill={entry.status === 'zero' ? '#b4232f' : entry.status === 'weak' ? '#a15c00' : cameraColors[entry.reader] || '#2563a7'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <aside className="grid gap-3">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h3 className="font-black">Lecteurs</h3>
            <p className="mt-1 text-xs text-slate-500">{camera.note} Total boites vues: {camera.total_boxes}.</p>
            <div className="mt-3 grid gap-2">
              {(camera.reader_stats || []).map((item) => (
                <div key={item.reader} className="rounded-md border border-slate-200 bg-white p-3">
                  <strong>{item.reader}</strong>
                  <p className="text-xs text-slate-500">Cameras attendues: {item.expected_cameras}</p>
                  <p className="text-sm">{item.zero_code_label} lectures a 0 code</p>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h3 className="font-black">Alertes cameras</h3>
            <div className="mt-3 grid gap-2">
              {(camera.alerts || []).length ? camera.alerts.map((item) => (
                <div
                  key={`${item.reader}-${item.camera}`}
                  className={`rounded-md border p-3 ${item.status === 'zero' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50'}`}
                >
                  <strong>{item.label}</strong>
                  <p className="text-sm">{item.status_label} ({item.success_count} reussite(s))</p>
                </div>
              )) : (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3">
                  <strong>Aucune camera a zero</strong>
                  <p className="text-sm text-slate-600">Toutes les cameras attendues contribuent dans cette trace.</p>
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function DetailList({ items }) {
  const values = (items || []).filter(Boolean);
  if (!values.length) return <p className="text-sm text-slate-500">Non renseigne.</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {values.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
    </ul>
  );
}

function DiagnosticCard({ group, index }) {
  const severity = fieldSeverity(group);
  return (
    <details className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <summary className="grid cursor-pointer gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div>
          <div className="flex flex-wrap gap-2">
            <SeverityBadge severity={severity} label={fieldSeverityLabel(group)} />
            <Badge className="border-slate-300 bg-slate-50 text-slate-700">{fieldZone(group)}</Badge>
            <Badge className="border-slate-300 bg-slate-50 text-slate-700">{group.belt} / {group.code}</Badge>
          </div>
          <h3 className="mt-3 text-base font-black">{index}. {fieldAction(group)}</h3>
          <p className="mt-2 text-sm">{fieldImpact(group)}</p>
          <p className="mt-2 text-xs text-slate-500">{group.evidence} | {group.incident_count} diagnostic(s)</p>
        </div>
        <div className="font-black text-blue-900 lg:text-right">{group.affected_label || group.metric}</div>
      </summary>
      <div className="border-t border-slate-200 bg-slate-50 p-4">
        <section className="mb-3 rounded-lg border border-slate-200 bg-white p-3">
          <h4 className="text-xs font-black uppercase text-slate-600">Lecture terrain</h4>
          <p className="mt-1 text-sm font-bold">{group.field_explanation || fieldImpact(group)}</p>
          <p className="mt-2 text-sm">{fieldAction(group)}</p>
        </section>
        <div className="grid gap-3 lg:grid-cols-2">
          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <h4 className="text-xs font-black uppercase text-slate-600">Constat</h4>
            <DetailList items={group.business_lines} />
          </section>
          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <h4 className="text-xs font-black uppercase text-slate-600">Impact probable</h4>
            <p className="text-sm">{fieldImpact(group)}</p>
          </section>
          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <h4 className="text-xs font-black uppercase text-slate-600">Causes probables</h4>
            <DetailList items={group.probable_causes} />
          </section>
          <section className="rounded-lg border border-slate-200 bg-white p-3">
            <h4 className="text-xs font-black uppercase text-slate-600">Controles a faire</h4>
            <DetailList items={group.checks} />
          </section>
        </div>
        <section className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
          <h4 className="text-xs font-black uppercase text-slate-600">Preuves trace</h4>
          {(group.incidents || []).slice(0, 3).map((incident) => (
            <article key={`${incident.first_line}-${incident.last_line}`} className="mt-3 border-t border-slate-100 pt-3 first:mt-0 first:border-t-0 first:pt-0">
              <strong>{incident.start_time_str} -&gt; {incident.end_time_str}</strong>
              <p className="text-xs text-slate-500">L.{incident.first_line} -&gt; L.{incident.last_line} | {incident.count} occurrence(s)</p>
              <p className="mt-1 text-sm">{incident.summary || '-'}</p>
              <p className="mt-2 font-mono text-xs text-slate-500">
                Lignes utiles: {(incident.event_lines || []).slice(0, 10).map((line) => `L.${line}`).join(', ') || '-'}
              </p>
            </article>
          ))}
        </section>
      </div>
    </details>
  );
}

function buildPdfLines(data) {
  const lines = [
    { kind: 'hero', text: `${data.verdict.label} - ${data.verdict.title}`, size: 16, bold: true, gap: 54 },
    { text: data.verdict.text, size: 10, gap: 18 },
    { text: `Critiques: ${data.counts.error} | Alertes: ${data.counts.warning} | Infos: ${data.counts.info} | Types: ${data.counts.types}`, size: 10, bold: true, gap: 26 },
    { kind: 'section', text: 'Actions prioritaires', size: 13, bold: true, gap: 24 },
  ];
  data.priority.forEach((group, index) => {
    lines.push({ kind: 'group', severity: fieldSeverity(group), text: `${index + 1}. [${fieldSeverityLabel(group)}] ${fieldZone(group)} - ${fieldAction(group)}`, size: 10, bold: true, gap: 24 });
    lines.push({ text: `${group.affected_label || group.metric} | ${group.evidence}`, size: 9, gap: 12 });
    wrapText(fieldImpact(group), 92).forEach((line) => lines.push({ text: line, size: 9, gap: 10 }));
    wrapText(group.field_explanation || fieldAction(group), 92).forEach((line) => lines.push({ text: line, size: 9, gap: 10 }));
    (group.checks || []).slice(0, 3).forEach((check) => {
      wrapText(`Controle: ${check}`, 90).forEach((line) => lines.push({ text: line, size: 9, gap: 10 }));
    });
    lines.push({ text: '', size: 9, gap: 7 });
  });
  if (data.camera?.available) {
    lines.push({ kind: 'section', text: 'Lecture cameras', size: 13, bold: true, gap: 24 });
    (data.camera.chart || []).slice(0, 8).forEach((item) => {
      lines.push({ text: `${item.label}: ${item.success_count} lecture(s) reussie(s) - ${item.status_label}`, size: 9, gap: 11 });
    });
    (data.camera.reader_stats || []).forEach((item) => {
      lines.push({ text: `${item.reader}: ${item.zero_code_label} lectures a 0 code, cameras ${item.expected_cameras}`, size: 9, gap: 11 });
    });
    lines.push({ text: '', size: 9, gap: 7 });
  }
  lines.push({ kind: 'section', text: 'Diagnostics par zone', size: 13, bold: true, gap: 24 });
  data.groups.forEach((group, index) => {
    lines.push({ kind: 'group', severity: fieldSeverity(group), text: `${index + 1}. [${fieldSeverityLabel(group)}] ${fieldZone(group)} - ${fieldAction(group)}`, size: 10, bold: true, gap: 24 });
    lines.push({ text: `${group.affected_label || group.metric} | ${group.evidence}`, size: 9, gap: 12 });
    wrapText(fieldImpact(group), 92).forEach((line) => lines.push({ text: line, size: 9, gap: 10 }));
    lines.push({ text: '', size: 9, gap: 7 });
  });
  return lines;
}

function pdfEscape(text) {
  return String(text ?? '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\x20-\x7E]/g, ' ')
    .replace(/\\/g, '\\\\')
    .replace(/\(/g, '\\(')
    .replace(/\)/g, '\\)');
}

function wrapText(text, maxChars) {
  const words = String(text ?? '').replace(/\s+/g, ' ').trim().split(' ');
  const lines = [];
  let line = '';
  words.forEach((word) => {
    if (!word) return;
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  });
  if (line) lines.push(line);
  return lines.length ? lines : [''];
}

function pdfTextLine(text, x, y, size = 10, bold = false) {
  const font = bold ? 'F2' : 'F1';
  return `BT /${font} ${size} Tf ${x} ${y} Td (${pdfEscape(text)}) Tj ET\n`;
}

function pdfRect(x, y, w, h, color = '0.97 0.98 0.99', stroke = '0.80 0.84 0.88') {
  return `q ${color} rg ${stroke} RG ${x} ${y} ${w} ${h} re B Q\n`;
}

function pdfRule(x, y, w, color = '0.72 0.76 0.80') {
  return `q ${color} RG ${x} ${y} m ${x + w} ${y} l S Q\n`;
}

function pdfSeverityColor(severity) {
  if (severity === 'error') return '1 0.93 0.94';
  if (severity === 'warning') return '1 0.97 0.88';
  return '0.93 0.96 1';
}

function buildPdf(lines) {
  const pageWidth = 595;
  const pageHeight = 842;
  const marginLeft = 42;
  const marginTop = 770;
  const bottom = 58;
  const pages = [];
  let y = marginTop;
  let content = '';
  let pageNo = 1;

  const footer = () => {
    content += pdfRule(42, 52, 511, '0.82 0.85 0.88');
    content += pdfTextLine(`TraceAlphaViewer - page ${pageNo}`, 42, 35, 8, false);
  };
  const newPage = () => {
    footer();
    pages.push(content);
    content = pdfTextLine('Rapport diagnostic terrain', 42, 808, 14, true);
    y = marginTop;
    pageNo += 1;
  };

  content += pdfRect(36, 782, 523, 48, '0.93 0.96 1', '0.72 0.80 0.90');
  content += pdfTextLine('Rapport diagnostic terrain TraceAlphaViewer', 48, 808, 16, true);

  lines.forEach((item) => {
    if (item.kind === 'hero') {
      if (y - 54 < bottom) newPage();
      content += pdfRect(42, y - 38, 511, 42);
      content += pdfTextLine(item.text, 54, y - 12, item.size, true);
      y -= item.gap;
      return;
    }
    if (item.kind === 'section') {
      if (y - 30 < bottom) newPage();
      content += pdfRule(42, y + 6, 511);
      content += pdfTextLine(item.text, 42, y - 10, item.size, true);
      y -= item.gap;
      return;
    }
    if (item.kind === 'group') {
      if (y - 54 < bottom) newPage();
      content += pdfRect(42, y - 42, 511, 46, pdfSeverityColor(item.severity));
      content += pdfTextLine(item.text, 54, y - 12, item.size, true);
      y -= item.gap;
      return;
    }
    wrapText(item.text, item.size >= 13 ? 70 : 96).forEach((line, idx, arr) => {
      const gap = idx === arr.length - 1 ? item.gap : Math.max(10, item.size + 2);
      if (y - gap < bottom) newPage();
      content += pdfTextLine(line, marginLeft, y, item.size, item.bold);
      y -= gap;
    });
  });
  if (content) {
    footer();
    pages.push(content);
  }

  const objects = [];
  const addObject = (body) => {
    objects.push(body);
    return objects.length;
  };
  const fontRegularId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
  const fontBoldId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>');
  const pageIds = [];
  const pagePlaceholders = [];
  pages.forEach((pageContent) => {
    const stream = `<< /Length ${pageContent.length} >>\nstream\n${pageContent}endstream`;
    const contentId = addObject(stream);
    const placeholder = `__PARENT_${pageIds.length}__`;
    const pageId = addObject(
      `<< /Type /Page /Parent ${placeholder} 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] ` +
      `/Resources << /Font << /F1 ${fontRegularId} 0 R /F2 ${fontBoldId} 0 R >> >> ` +
      `/Contents ${contentId} 0 R >>`,
    );
    pageIds.push(pageId);
    pagePlaceholders.push(placeholder);
  });
  const pagesId = addObject(`<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageIds.length} >>`);
  const catalogId = addObject(`<< /Type /Catalog /Pages ${pagesId} 0 R >>`);
  pagePlaceholders.forEach((placeholder, idx) => {
    const pageObjectId = pageIds[idx];
    objects[pageObjectId - 1] = objects[pageObjectId - 1].replace(placeholder, String(pagesId));
  });
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((body, idx) => {
    offsets.push(pdf.length);
    pdf += `${idx + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let idx = 1; idx <= objects.length; idx += 1) {
    pdf += `${String(offsets[idx]).padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return pdf;
}

function downloadPdf(data) {
  const pdf = buildPdf(buildPdfLines(data));
  const blob = new Blob([pdf], { type: 'application/pdf' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '');
  link.href = url;
  link.download = `diagnostic_terrain_${stamp}.pdf`;
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    link.remove();
  }, 1000);
}

export default function ReportPage() {
  const [data, setData] = useState(emptyData);
  const [activeFilter, setActiveFilter] = useState('all');
  const [search, setSearch] = useState('');

  useEffect(() => {
    setData(window.__TRACE_REPORT_DATA__ || emptyData);
  }, []);

  const filteredGroups = useMemo(() => {
    const text = search.trim().toLowerCase();
    return (data.groups || []).filter((group) => {
      const quickOk = activeFilter === 'all'
        || (activeFilter === 'critical' && fieldSeverity(group) === 'error')
        || group.family === activeFilter;
      const haystack = `${fieldSeverityLabel(group)} ${fieldZone(group)} ${group.belt} ${group.code} ${group.title} ${fieldAction(group)} ${fieldImpact(group)} ${group.field_explanation || ''} ${group.summary} ${(group.business_lines || []).join(' ')}`.toLowerCase();
      return quickOk && (!text || haystack.includes(text));
    });
  }, [data.groups, activeFilter, search]);

  const filterItems = data.families?.length
    ? data.families
    : [
      { id: 'all', label: 'Tout' },
      { id: 'critical', label: 'Critique' },
      { id: 't2', label: 'T2/C4/T3' },
      { id: 't4', label: 'T4/C6' },
      { id: 't5', label: 'T5/C9' },
      { id: 'camera', label: 'Cameras' },
      { id: 'dimensions', label: 'Dimensions' },
    ];

  const setFilter = (id) => {
    setActiveFilter(id);
    if (id === 'camera') {
      requestAnimationFrame(() => document.getElementById('camera-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    }
  };

  return (
    <main className="mx-auto max-w-[1440px] p-5">
      <header className="no-print sticky top-0 z-20 -mx-5 -mt-5 mb-5 flex items-center justify-between gap-4 border-b border-slate-200 bg-white/95 px-6 py-4 shadow-sm">
        <div>
          <div className="text-xs font-black uppercase tracking-wide text-slate-500">TraceAlphaViewer</div>
          <h1 className="text-2xl font-black">Rapport diagnostic terrain</h1>
          <p className="text-sm text-slate-500">Genere le {data.generated_at}</p>
        </div>
        <button
          type="button"
          onClick={() => downloadPdf(data)}
          className="rounded-lg bg-blue-900 px-4 py-2 font-black text-white shadow-sm"
        >
          Exporter PDF
        </button>
      </header>

      <section className={`rounded-lg border-l-8 p-5 shadow-sm ${verdictStyles[data.verdict.level] || verdictStyles.ok}`}>
        <div className="flex flex-wrap items-center gap-4">
          <span className="rounded-md bg-slate-950 px-3 py-2 text-sm font-black text-white">{data.verdict.label}</span>
          <div>
            <h2 className="text-xl font-black">{data.verdict.title}</h2>
            <p className="text-sm text-slate-600">{data.verdict.text}</p>
          </div>
          <strong className="ml-auto text-lg">{data.counts.types} type(s)</strong>
        </div>
      </section>

      <section className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label="Critiques terrain" value={data.counts.error} />
        <StatCard label="Alertes terrain" value={data.counts.warning} />
        <StatCard label="Infos terrain" value={data.counts.info} />
        <StatCard label="Incidents" value={data.counts.incidents} />
        <StatCard label="Boites vues" value={data.counts.total_boxes || '-'} />
      </section>

      <section className="mt-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs font-black uppercase tracking-wide text-slate-500">A traiter en premier</div>
            <h2 className="text-lg font-black">Priorites terrain</h2>
          </div>
          <p className="text-sm text-slate-500">Tri par criticite terrain, volume et code metier.</p>
        </div>
        <div className="mt-4">
          <PriorityTable groups={data.priority || []} />
        </div>
      </section>

      <section className="mt-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-black">Zones a controler</h2>
        <div className="mt-2 grid gap-x-6 md:grid-cols-2 xl:grid-cols-3">
          {(data.zones || []).length
            ? data.zones.map((zone) => <ZoneCard key={zone.family} zone={zone} />)
            : <p className="mt-2 text-sm text-slate-500">Aucune zone en anomalie.</p>}
        </div>
      </section>

      <section className="no-print mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        {filterItems.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setFilter(item.id)}
            className={`rounded-lg border px-3 py-2 text-sm font-black ${activeFilter === item.id ? 'border-blue-900 bg-blue-900 text-white' : 'border-slate-200 bg-white text-slate-700'}`}
          >
            {item.label}
          </button>
        ))}
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="min-w-[280px] flex-1 rounded-lg border border-slate-200 px-3 py-2"
          placeholder="Rechercher zone, code, action, preuve..."
        />
        <span className="text-sm text-slate-500">{filteredGroups.length} diagnostic(s) visible(s)</span>
      </section>

      <div className="mt-4">
        <CameraPanel camera={data.camera} />
      </div>

      <section className="mt-4 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-lg font-black">Diagnostics detailles</h2>
          <p className="text-sm text-slate-500">Ouvrir une carte pour voir causes, controles et preuves.</p>
        </div>
        <div className="mt-4 grid gap-3">
          {filteredGroups.map((group, index) => (
            <DiagnosticCard key={`${group.code}-${group.first_line}-${group.last_line}`} group={group} index={index + 1} />
          ))}
        </div>
      </section>
    </main>
  );
}
