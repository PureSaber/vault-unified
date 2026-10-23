const paths = {
  vault: "M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm2 6h6m-3-3v6m-7 4h2m10 0h2",
  passwords: "M14 3a6 6 0 1 1-4.8 9.6L3 19v2h4v-3h3l2.4-2.4M16 7h.01",
  security: "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Zm-4 9 3 3 5-6",
  connections: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2m3 6a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
  sharing: "M15 8 20 3m0 0h-7m7 0v7M9 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-5M9 15l11-12",
  settings: "M4 7h16M4 17h16M8 4v6M16 14v6",
  lock: "M6 10h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Zm2 0V6a4 4 0 0 1 8 0v4m-4 5v2",
  search: "M10.5 3a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15Zm5.5 13 5 5",
  copy: "M8 8h12v13H8zM16 8V3H3v13h5",
  edit: "m4 15 11-11 5 5L9 20l-6 1 1-6Zm8-8 5 5",
  back: "m14 5-7 7 7 7M7 12h14",
  menu: "M4 6h16M4 12h16M4 18h16",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm7 0a3 3 0 1 0 6 0 3 3 0 0 0-6 0",
  more: "M5 12h.01M12 12h.01M19 12h.01",
} as const;
export type IconName = keyof typeof paths;
export default function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return <svg className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
