// Presentation aliases only. Provider IDs and protocols remain unchanged.
export const MUSIC_PLATFORMS = Object.freeze({ wy: '小云', tx: '小Q', kw: '小酷', kg: '小狗', mg: '小咪' })
export const canManageMusicSources = user => user?.can_manage === true

const aliases = [
  [/网易云(?:音乐)?|网易(?:音乐)?|netease/gi, MUSIC_PLATFORMS.wy],
  [/QQ\s*(?:音乐|music)?|腾讯(?:音乐)?|tencent/gi, MUSIC_PLATFORMS.tx],
  [/酷我(?:音乐)?|kuwo/gi, MUSIC_PLATFORMS.kw],
  [/酷狗(?:音乐)?|kugou/gi, MUSIC_PLATFORMS.kg],
  [/咪咕(?:音乐)?|migu/gi, MUSIC_PLATFORMS.mg],
]
export const musicDisplayName = value => aliases.reduce((text, [pattern, label]) => text.replace(pattern, label), String(value || ''))
