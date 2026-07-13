"""测试评论API结构 —— 临时脚本，用完即删"""
import requests, json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from bilispider.login import get_cookie_string
from bilispider.wbi import enc_wbi, get_wbi_keys

cookie = get_cookie_string()
img_key, sub_key = get_wbi_keys()

def signed_get(url, params, referer='https://www.bilibili.com/'):
    s = enc_wbi(params, img_key=img_key, sub_key=sub_key)
    h = {'User-Agent': 'Mozilla/5.0', 'Referer': referer, 'Cookie': cookie}
    return requests.get(url, params=s, headers=h, timeout=10).json()

# 1. 获取UP主最新视频
v = signed_get('https://api.bilibili.com/x/space/wbi/arc/search', {
    'mid':'2','ps':3,'tid':0,'pn':1,'keyword':'','order':'pubdate',
    'platform':'web','web_location':1550101,'order_avoided':'true'},
    referer='https://space.bilibili.com/2/video')
vlist = v['data']['list']['vlist']
for item in vlist:
    print(f"aid={item['aid']} bvid={item['bvid']} title={item['title'][:30]}")

# 2. 测试视频评论 (使用第三个视频避免热门视频的缓存干扰)
aid = vlist[-1]['aid']
print(f"\n=== 测试视频 aid={aid} ===")
r = signed_get('https://api.bilibili.com/x/v2/reply',
    {'type':1,'oid':aid,'pn':1,'ps':20,'sort':2})
if r.get('code') == 0:
    page = r['data']['page']
    replies = r['data'].get('replies', [])
    print(f"总评论: {page['count']}, 本页: {len(replies)}")
    if replies:
        c = replies[0]
        print(f"一级: rpid={c['rpid']} mid={c['mid']} time={c['ctime']} sub_replies={len(c.get('replies',[]))}")

        # 3. 测试子评论分页
        root = c['rpid']
        sr = signed_get('https://api.bilibili.com/x/v2/reply/reply',
            {'type':1,'oid':aid,'pn':1,'ps':20,'root':root})
        if sr.get('code') == 0:
            sp = sr['data'].get('page',{})
            print(f"子评论: 总数={sp.get('count',0)} 本页={len(sr['data'].get('replies',[]))}")
        else:
            print(f"子评论API错误: code={sr.get('code')}")

# 4. 测试翻页上限
for pn in [10, 20, 30, 50]:
    r2 = signed_get('https://api.bilibili.com/x/v2/reply',
        {'type':1,'oid':aid,'pn':pn,'ps':20,'sort':2})
    if r2.get('code') == 0:
        cnt = r2['data']['page'].get('count', 0)
        print(f"  翻页 pn={pn}: OK, 总评论={cnt}")
    else:
        print(f"  翻页 pn={pn}: code={r2.get('code')} msg={r2.get('message')}")
        break
else:
    print(f"  (pn>=50 未测试)")
