// 统一的缓出曲线,对应 tokens.css 的 --ease-standard 三次方落地感。
/** 三次方缓出:0..1 输入,前快后慢,用于所有入场与镜头运动。 */
export const easeOutCubic = (t: number): number => 1 - Math.pow(1 - t, 3);
