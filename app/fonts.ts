import localFont from 'next/font/local';

export const plexSans = localFont({
  src: [
    { path: '../public/fonts/IBMPlexSans-Regular.woff2', weight: '400', style: 'normal' },
    { path: '../public/fonts/IBMPlexSans-Bold.woff2', weight: '700', style: 'normal' },
  ],
  variable: '--font-plex-sans',
  display: 'swap',
});

export const plexMono = localFont({
  src: [
    { path: '../public/fonts/IBMPlexMono-Regular.woff2', weight: '400', style: 'normal' },
  ],
  variable: '--font-plex-mono',
  display: 'swap',
});
