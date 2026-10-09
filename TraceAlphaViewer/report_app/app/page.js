'use client';

import { useEffect, useRef } from 'react';
import '../public/report-ui.js';

export default function ReportPage() {
  const root = useRef(null);
  useEffect(() => {
    return globalThis.TraceReport.mount(root.current, window.__TRACE_REPORT_DATA__ || {});
  }, []);
  return <div ref={root} />;
}
