"""Pinned CSI500 June2021 official constituent-change supplement.

Only this event is certified here; this is neither a daily membership history
nor a weight repair. Original source bytes were independently reconciled before
transcription. Attachment paths do not establish their historical release time.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _IndexChangePatch:
    patch_id: str
    version: int
    symbol: str
    notice_id: int
    notice_url: str
    notice_sha256: str
    attachment_url: str
    attachment_sha256: str
    calendar_url: str
    calendar_sha256: str
    observed_at_utc: str
    announcement_date: str
    effective_after_close: str
    first_session: str
    added: tuple[tuple[str, str], ...]
    removed: tuple[tuple[str, str], ...]
    records_sha256: str


PATCH = _IndexChangePatch(
    patch_id="CSI_000905_20210615_V1",
    version=1,
    symbol="000905.SH",
    notice_id=12470,
    notice_url="https://www.csindex.com.cn/#/about/newsDetail?id=12470",
    notice_sha256="b00c27760911aeab0435d32533082cf7fca8a4abe510d6187a3180e3a70a0a96",
    attachment_url=(
        "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/info/"
        "files/20210610/1623319091660435.xlsx"
    ),
    attachment_sha256="07e8c58d5f02cbaaf5e5b4a98f7c541208218d7a3de9b9627fbff37f31770a07",
    calendar_url=(
        "https://www.sse.com.cn/disclosure/announcement/general/c/"
        "c_20210603_5481611.shtml"
    ),
    calendar_sha256="dec94944dceb702a0dfe79a79e3c162a9ad2b3495955203d4d1c5df81be447a6",
    observed_at_utc="2026-10-15T07:22:16.780276+00:00",
    announcement_date="2021-05-28",
    effective_after_close="2021-06-11T15:00:00",
    first_session="2021-06-15",
    added=(
        ('000671.SZ', '阳光城'),
        ('000723.SZ', '美锦能源'),
        ('000799.SZ', '酒鬼酒'),
        ('000961.SZ', '中南建设'),
        ('002065.SZ', '东华软件'),
        ('002127.SZ', '南极电商'),
        ('002146.SZ', '荣盛发展'),
        ('002180.SZ', '纳思达'),
        ('002422.SZ', '科伦药业'),
        ('002439.SZ', '启明星辰'),
        ('002532.SZ', '天山铝业'),
        ('002958.SZ', '青农商行'),
        ('003022.SZ', '联泓新科'),
        ('003035.SZ', '南网能源'),
        ('300037.SZ', '新宙邦'),
        ('300251.SZ', '光线传媒'),
        ('300253.SZ', '卫宁健康'),
        ('300308.SZ', '中际旭创'),
        ('300383.SZ', '光环新网'),
        ('300741.SZ', '华宝股份'),
        ('600027.SH', '华电国际'),
        ('600066.SH', '宇通客车'),
        ('600068.SH', '葛洲坝'),
        ('600095.SH', '湘财股份'),
        ('600177.SH', '雅戈尔'),
        ('600208.SH', '新湖中宝'),
        ('600271.SH', '航天信息'),
        ('600369.SH', '西南证券'),
        ('600377.SH', '宁沪高速'),
        ('600390.SH', '五矿资本'),
        ('600487.SH', '亨通光电'),
        ('600498.SH', '烽火通信'),
        ('600536.SH', '中国软件'),
        ('600637.SH', '东方明珠'),
        ('600663.SH', '陆家嘴'),
        ('600732.SH', '爱旭股份'),
        ('600803.SH', '新奥股份'),
        ('600988.SH', '赤峰黄金'),
        ('600998.SH', '九州通'),
        ('601117.SH', '中国化学'),
        ('601187.SH', '厦门银行'),
        ('601198.SH', '东兴证券'),
        ('601568.SH', '北元集团'),
        ('601577.SH', '长沙银行'),
        ('601636.SH', '旗滨集团'),
        ('601991.SH', '大唐发电'),
        ('603156.SH', '养元饮品'),
        ('603707.SH', '健友股份'),
        ('605358.SH', '立昂微'),
        ('688208.SH', '道通科技'),
    ),
    removed=(
        ('000008.SZ', '神州高铁'),
        ('000301.SZ', '东方盛虹'),
        ('000543.SZ', '皖能电力'),
        ('000600.SZ', '建投能源'),
        ('002051.SZ', '中工国际'),
        ('002064.SZ', '华峰化学'),
        ('002093.SZ', '国脉科技'),
        ('002217.SZ', '合力泰'),
        ('002503.SZ', '搜于特'),
        ('002544.SZ', '杰赛科技'),
        ('002568.SZ', '百润股份'),
        ('002589.SZ', '瑞康医药'),
        ('002640.SZ', '*ST跨境'),
        ('002791.SZ', '坚朗五金'),
        ('002807.SZ', '江阴银行'),
        ('002920.SZ', '德赛西威'),
        ('002941.SZ', '新疆交建'),
        ('002957.SZ', '科瑞技术'),
        ('300012.SZ', '华测检测'),
        ('300134.SZ', '大富科技'),
        ('300274.SZ', '阳光电源'),
        ('300324.SZ', '旋极信息'),
        ('300459.SZ', '金科文化'),
        ('300496.SZ', '中科创达'),
        ('300595.SZ', '欧普康视'),
        ('600053.SH', '九鼎投资'),
        ('600073.SH', '上海梅林'),
        ('600079.SH', '人福医药'),
        ('600132.SH', '重庆啤酒'),
        ('600143.SH', '金发科技'),
        ('600273.SH', '嘉化能源'),
        ('600277.SH', '亿利洁能'),
        ('600291.SH', '*ST西水'),
        ('600338.SH', '西藏珠峰'),
        ('600426.SH', '华鲁恒升'),
        ('600545.SH', '卓郎智能'),
        ('600575.SH', '淮河能源'),
        ('600664.SH', '哈药股份'),
        ('600675.SH', '中华企业'),
        ('600748.SH', '上实发展'),
        ('600869.SH', '远东股份'),
        ('601799.SH', '星宇股份'),
        ('601865.SH', '福莱特'),
        ('601966.SH', '玲珑轮胎'),
        ('603328.SH', '依顿电子'),
        ('603338.SH', '浙江鼎力'),
        ('603345.SH', '安井食品'),
        ('603806.SH', '福斯特'),
        ('603816.SH', '顾家家居'),
        ('603882.SH', '金域医学'),
    ),
    records_sha256="6594e6c9a674fa59bced11b937ed851d1da49d6a4a3c23951550e2a2d75760fc",
)
