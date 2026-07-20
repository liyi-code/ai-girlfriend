"""字节 Seed-TTS（火山引擎「豆包语音合成大模型 2.0 / seed-tts-2.0」）的 5 种 AI 音色预设。

全部是「官方 AI 合成音色」，不克隆任何真人/角色声线，无 IP / 肖像权隐患，
适合参赛分发、用户零配置（只需一个火山引擎 Key + 开通 seed-tts-2.0 计费）。

每个角色映射到火山引擎 seed-tts-2.0 资源下「已实测可用」的官方 voice_id
（uranus / saturn / saturn_tob 三种后缀都属于 seed-tts-2.0 资源，均可直连）。
若某音色在你的火山引擎账号里不可用 / 想换，直接改下面的 voice_id 即可
（在火山引擎控制台「豆包语音合成大模型」里能看到你账号下可用的 voice_type）。

已实测可用的官方音色池（seed-tts-2.0 资源）：
  女声：zh_female_vv_uranus_bigtts(vivi) / zh_female_xiaohe_uranus_bigtts(小何) /
        zh_female_cancan_uranus_bigtts(灿灿) / zh_female_mizai_saturn_bigtts(咪仔) /
        zh_female_jitangnv_saturn_bigtts(鸡汤女) / zh_female_meilinvyou_saturn_bigtts(魅力女友) /
        zh_female_santongyongns_saturn_bigtts(流畅女声) / zh_female_xueayi_saturn_bigtts(儿童绘本) /
        saturn_zh_female_cancan_tob(知性灿灿) / saturn_zh_female_keainvsheng_tob(可爱女生) /
        saturn_zh_female_tiaopigongzhu_tob(调皮公主)
  男声：zh_male_liufei_uranus_bigtts(刘飞) / zh_male_m191_uranus_bigtts(云舟) /
        zh_male_taocheng_uranus_bigtts(小天) / zh_male_dayi_saturn_bigtts(大壹) /
        zh_male_ruyayichen_saturn_bigtts(儒雅逸辰) / saturn_zh_male_shuanglangshaonian_tob(爽朗少年) /
        saturn_zh_male_tiancaitongzhuo_tob(天才同桌)
"""

SEEDTTS_PRESETS = {
    "qingleng_yujie": {
        "name": "清冷御姐",
        # vivi：成熟知性御姐感，语气偏冷但温柔，最贴合「清冷御姐」人设
        "voice_id": "zh_female_vv_uranus_bigtts",
    },
    "xie_yujie": {
        "name": "屑御姐",
        # 调皮公主：俏皮、傲娇、带点小恶魔感，正好是「屑御姐」的味道
        "voice_id": "saturn_zh_female_tiaopigongzhu_tob",
    },
    "keai_luoli": {
        "name": "可爱萝莉",
        # 灿灿：年轻可爱、软糯，萝莉感足
        "voice_id": "zh_female_cancan_uranus_bigtts",
    },
    "zhengtai": {
        "name": "正太",
        # 天才同桌：少年感、清亮，像聪明的小正太
        "voice_id": "saturn_zh_male_tiancaitongzhuo_tob",
    },
    "chengnan": {
        "name": "成男",
        # 刘飞：成熟稳重男声，适合「成男」人设
        "voice_id": "zh_male_liufei_uranus_bigtts",
    },
}
DEFAULT_VOICE = "qingleng_yujie"
