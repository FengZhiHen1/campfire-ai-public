/** 产品共用的单色图标；尺寸与颜色继承使用位置，不引入图标依赖。 */
export function Icon({ name }: { name: 'arrow' | 'send' | 'plus' | 'book' | 'person' | 'shield' | 'chat' | 'chevron' }) {
  const paths = {
    arrow: 'M5 12h14M13 6l6 6-6 6',
    send: 'M12 19V5M6 11l6-6 6 6',
    plus: 'M12 5v14M5 12h14',
    book: 'M12 6v14M12 6C8 3 3 4 3 4v14s5-1 9 2c4-3 9-2 9-2V4s-5-1-9 2Z',
    person: 'M8 7a4 4 0 1 0 8 0 4 4 0 0 0-8 0ZM4 21v-2a8 8 0 0 1 16 0v2',
    shield: 'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3ZM8 12l3 3 5-6',
    chat: 'M4 5h16v12H9l-5 4V5Z',
    chevron: 'm9 5 7 7-7 7',
  };
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  );
}
