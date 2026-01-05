import os
import re
import requests
from datetime import datetime
from collections import defaultdict
from pathlib import Path
import time

# ================== 配置区 ==================
DRY_RUN = True  # True = 只打印不上传，False = 实际上传
BASE_DIR = "我的动态"
EMAIL = ""  # 填写账号邮箱。如果账号是qq则请自动补全为qq邮箱填写
PASSWORD = ""

START_DATE_STR = "2021-09-01"
END_DATE_STR = "2025-12-10"
START_DATE = datetime.strptime(
    START_DATE_STR, "%Y-%m-%d").date() if START_DATE_STR else None
END_DATE = datetime.strptime(
    END_DATE_STR, "%Y-%m-%d").date() if END_DATE_STR else None
# ============================================

# API 地址
LOGIN_URL = "https://nideriji.cn/api/login/"
UPLOAD_IMAGE_URL = "https://f.nideriji.cn/api/upload_image/"
WRITE_DIARY_URL = "https://nideriji.cn/api/write/"

# ========== 工具函数 ==========


def parse_text_file(path):
    """解析动态文本文件，返回每天的条目，支持中文/英文冒号的图片格式"""
    result = defaultdict(list)
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.rstrip() for l in f]

    date = time_str = None
    text_lines = []
    images = []

    def flush():
        if date and time_str:
            result[date].append({
                "time": time_str,
                "text": "\n".join(text_lines).strip(),
                "images": images.copy()
            })

    for line in lines + [""]:
        # 匹配日期时间行
        m = re.match(r"(\d{4})年(\d{2})月(\d{2})日 (\d{2}:\d{2}:\d{2})", line)
        if m:
            flush()
            y, mo, d, t = m.groups()
            date = f"{y}-{mo}-{d}"
            time_str = t
            text_lines.clear()
            images.clear()
            continue

        # 匹配图片行，支持中文/英文冒号
        m = re.match(r"\s*\[图片[:：](.*?)\]", line)
        if m:
            images.append(m.group(1).strip())
            continue

        if line.strip() != "":
            text_lines.append(line)

    flush()
    return result


def merge_day(entries):
    """合并同一天多条日记为完整正文 + 图片列表"""
    texts = []
    all_images = []
    for e in entries:
        texts.append(f"[{e['time'][:5]}]\n{e['text']}".strip())

        all_images.extend(e["images"])
    return "\n\n".join(texts), all_images


def login(session):
    """登录获取 token"""
    try:
        resp = session.post(
            LOGIN_URL,
            data={"email": EMAIL, "password": PASSWORD},  # 使用 data 不是 json
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("error", 0) != 0:
            raise Exception("登录失败")

        token = data.get("token")
        user_id = data.get("userid")

        if not token:
            raise Exception("登录失败，没有获取到 token")

        print(f"✅ 登录成功")
        print(f"   用户ID: {user_id}")
        print(f"   昵称: {data['user_config']['name']}")
        print(f"   现有日记数: {data['user_config']['diary_count']}")

        return token, user_id

    except Exception as e:
        raise Exception(f"登录失败: {e}")


def upload_image(session, img_path):
    """上传图片，返回图片 ID"""
    if not os.path.exists(img_path):
        print(f"图片不存在: {img_path}")
        return None

    try:
        with open(img_path, "rb") as f:
            files = {"image": (os.path.basename(img_path), f, "image/jpeg")}
            resp = session.post(UPLOAD_IMAGE_URL, files=files, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        img_id = data.get("image_id")
        if not img_id:
            print(f"上传失败，响应: {data}")
            return None
        return img_id
    except Exception as e:
        print(f"上传图片异常: {e}")
        return None


def write_diary(session, date, content):
    """写入日记"""
    try:
        resp = session.post(
            WRITE_DIARY_URL,
            data={"content": content, "date": date},
            timeout=15
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"写入失败: {e}")
        return False


def find_image_path(base_dir, year, img_filename):
    """
    查找图片文件路径
    """
    # 从文件名提取月份
    month_match = re.match(r'\d{4}(\d{2})\d{2}', img_filename)
    if month_match:
        month_num = int(month_match.group(1))
        month_name = f"{month_num}月"
    else:
        print(f"无法从文件名提取月份: {img_filename}")
        return None

    # 2022年的文件夹名不同
    if year == "2022":
        image_base = os.path.join(base_dir, f"{year}年", "图片&视频 - 副本")
    else:
        image_base = os.path.join(base_dir, f"{year}年", "图片&视频")

    img_path = os.path.join(image_base, month_name, img_filename)

    if not os.path.exists(img_path):
        print(f"路径不存在: {img_path}")
        return None
    return img_path


# ========== 主函数 ==========

def main():
    print("\n" + "=" * 60)
    print("可话日记迁移工具")
    print("=" * 60)
    print(f"时间范围: {START_DATE_STR} 至 {END_DATE_STR}")
    print(f"模式: {'预览模式（不会实际上传）' if DRY_RUN else '正式上传模式'}")
    print("=" * 60 + "\n")

    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "User-Agent": "OhApp/3.6.12 Platform/Android"
    })

    # 登录
    if not DRY_RUN:
        token, user_id = login(session)
        session.headers.update({"auth": f"token {token}"})
    else:
        print("预览模式，跳过登录\n")

    all_days = defaultdict(list)
    base_path = Path(BASE_DIR)
    for year_dir in base_path.iterdir():
        if not year_dir.is_dir() or not year_dir.name.endswith("年"):
            continue

        year = year_dir.name.replace("年", "")
        txt_file = year_dir / f"{year}年-动态内容.txt"

        if not txt_file.exists():
            print(f"未找到: {txt_file}")
            continue

        print(f"📖 读取: {txt_file.name}")
        parsed = parse_text_file(str(txt_file))

        for day, entries in parsed.items():
            all_days[day].extend(entries)

    print(f"\n共找到 {len(all_days)} 天的日记\n")

    for day in sorted(all_days.keys()):
        try:
            day_date = datetime.strptime(day, "%Y-%m-%d").date()
        except Exception:
            print(f"跳过非法日期: {day}")
            continue

        if START_DATE and day_date < START_DATE:
            continue
        if END_DATE and day_date > END_DATE:
            continue

        entries = all_days[day]
        year = day.split("-")[0]

        content, images = merge_day(entries)

        print(f"\n📅 {day} ({len(entries)} 条)")
        print(
            f"内容预览: {content[:100].replace('\n', ' ')}{'...' if len(content) > 100 else ''}")
        print(f"图片数量: {len(images)} 张")

        image_ids = []
        if images:
            print("上传图片:")
            for idx, img_name in enumerate(images, 1):
                img_path = find_image_path(BASE_DIR, year, img_name)
                if not img_path:
                    print(f"  [{idx}/{len(images)}]  找不到: {img_name}")
                    continue

                print(f"  [{idx}/{len(images)}] {img_name}...", end=" ")
                img_id = upload_image(session, img_path)
                if img_id:
                    image_ids.append(img_id)
                    print(f"✓ (ID: {img_id})")
                else:
                    print("✗")
                time.sleep(0.5)

        # 替换正文中的图片为 [图ID]
        if image_ids:
            content += "\n\n"
            for img_id in image_ids:
                content += f"[图{img_id}]\n"

        print("写入日记...", end=" ")
        if write_diary(session, day, content):
            print("✓")
        else:
            print("✗")
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n错误: {e}")
