import './globals.css';

export const metadata = {
  title: 'Rapport diagnostic TraceAlphaViewer',
  description: 'Rapport terrain diagnostic Alpha',
};

export default function RootLayout({ children }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
