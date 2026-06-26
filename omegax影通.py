import requests
import time
import csv
import os
import subprocess
import threading
from datetime import datetime

# ================== 配置 ==================
PRODUCT_ID = 230
PRODUCT_NAME = "오메가엑스 1:1 VIDEO CALL EVENT"

# 要监控的选项及其自定义 CSV 文件名（只监控这些选项，其他忽略）
# 格式：{"选项名称": "自定义文件名.csv"}
# 如果字典为空，则监控所有选项（保持原行为）
MONITOR_OPTIONS = {
    "세빈": "SEBIN影通.csv",
    "예찬": "YECHAN影通.csv",
    "제현": "JEHYUN影通.csv",
    "휘찬": "HWICHAN影通.csv",
    "XEN": "XEN影通.csv",
    "KEVIN": "KEVIN影通.csv",
    "재한": "JAEHAN影通.csv"
}

# 数据检查间隔（秒）
CHECK_INTERVAL = 10
# 定时推送间隔（秒）
PUSH_INTERVAL = 60

# GitHub 配置（请修改为您自己的仓库信息）
GITHUB_REPO = "Juineii/omegax_ns0701"    # 例如 "Juineii/ive_k40625"
GITHUB_BRANCH = "main"                     # 分支名

# ================== 目录设置 ==================
# CSV 存放目录：当前脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = SCRIPT_DIR
os.makedirs(CSV_DIR, exist_ok=True)        # 确保目录存在（通常已存在）

# 全局变量
prev_stock = {}                     # 记录上次库存
lines_since_last_push = 0           # 自上次推送后新增的记录数
lines_lock = threading.Lock()
file_lock = threading.Lock()        # 用于推送时禁止写入，保证文件完整性


# ================== Git 推送函数（不变） ==================
def git_push_update():
    """
    将 CSV_DIR 目录下的所有变更提交并推送到 GitHub
    返回: True 表示推送成功（或无变化），False 表示失败
    """
    try:
        token = os.environ.get('GITHUB_TOKEN')
        if not token:
            print("⚠️ 环境变量 GITHUB_TOKEN 未设置，跳过 Git 推送")
            return False

        original_cwd = os.getcwd()
        os.chdir(CSV_DIR)

        remote_url = f"https://{token}@github.com/{GITHUB_REPO}.git"

        subprocess.run(['git', 'add', '.'], check=True, capture_output=True, timeout=30)

        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], capture_output=True, timeout=30)
        if result.returncode != 0:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            commit_msg = f"自动更新库存数据 {timestamp}"
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True, timeout=30)

            subprocess.run(
                ['git', 'push', remote_url, f'HEAD:{GITHUB_BRANCH}'],
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            print(f"✅ 已推送到 GitHub: {commit_msg}")
            os.chdir(original_cwd)
            return True
        else:
            print("⏭️ CSV 文件无变化，跳过推送")
            os.chdir(original_cwd)
            return True

    except subprocess.TimeoutExpired:
        print("❌ Git 操作超时 (30秒)，推送失败")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Git 操作失败: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        print(f"❌ 推送过程中发生错误: {e}")
        return False
    finally:
        if 'original_cwd' in locals():
            os.chdir(original_cwd)


# ================== 获取商品数据（不变） ==================
def fetch_product_data():
    url = f"https://shop-api.novera.town/v1/products/{PRODUCT_ID}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"请求失败: {e}")
        return None


# ================== 保存到 CSV（已移除“选项名称”列） ==================
def save_to_csv(csv_filename, timestamp, stock_change, sold_count):
    """
    按自定义文件名保存 CSV，文件位于脚本目录
    CSV 表头：时间, 商品名称, 库存变化, 单笔销量
    """
    global lines_since_last_push

    # 确保文件名以 .csv 结尾（如果用户未加则自动补上）
    if not csv_filename.endswith('.csv'):
        csv_filename += '.csv'

    csv_file = os.path.join(CSV_DIR, csv_filename)
    fieldnames = ["时间", "商品名称", "库存变化", "单笔销量"]   # 已移除“选项名称”
    file_exists = os.path.exists(csv_file)

    with file_lock:
        with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "时间": timestamp,
                "商品名称": PRODUCT_NAME,
                "库存变化": stock_change,
                "单笔销量": sold_count
            })

    print(f"{timestamp} - {csv_filename}: {stock_change}, 销量: {sold_count}")

    with lines_lock:
        lines_since_last_push += 1


# ================== 定时推送线程（不变） ==================
def push_worker():
    global lines_since_last_push
    while True:
        time.sleep(PUSH_INTERVAL)
        with lines_lock:
            pending = lines_since_last_push
        if pending > 0:
            print(f"⏰ 定时推送：有 {pending} 条新数据待推送")
            with file_lock:
                success = git_push_update()
            if success:
                with lines_lock:
                    lines_since_last_push = 0
                print("✅ 推送成功，计数器已归零")
            else:
                print("⚠️ 推送失败，下次再试")


# ================== 主监控循环 ==================
def main():
    global prev_stock, lines_since_last_push

    print(f"开始监控商品: {PRODUCT_NAME} (ID: {PRODUCT_ID})")
    print(f"数据将保存到: {CSV_DIR}")
    print(f"定时推送间隔: {PUSH_INTERVAL} 秒")

    # 检查是否配置了监控选项
    if MONITOR_OPTIONS:
        print("只监控以下选项：")
        for opt, fname in MONITOR_OPTIONS.items():
            print(f"  {opt} -> {fname}")
    else:
        print("未指定监控选项（MONITOR_OPTIONS 为空），将监控所有选项（原行为）")

    if not os.path.exists(os.path.join(CSV_DIR, ".git")):
        print("⚠️ 警告: CSV 目录不是 Git 仓库，请先执行 'git init' 并设置 remote origin。")

    push_thread = threading.Thread(target=push_worker, daemon=True)
    push_thread.start()

    while True:
        try:
            data = fetch_product_data()
            if not data:
                time.sleep(CHECK_INTERVAL)
                continue

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            combinations = data.get('optionCombinations', [])

            for combo in combinations:
                option_name = combo.get('optionName')
                stock = combo.get('stock')

                if option_name is None or stock is None:
                    continue

                # 只处理指定选项
                if MONITOR_OPTIONS:
                    if option_name not in MONITOR_OPTIONS:
                        continue   # 忽略未指定的选项
                    csv_filename = MONITOR_OPTIONS[option_name]
                else:
                    # 未指定监控列表时，使用选项名作为文件名（原行为）
                    csv_filename = option_name.replace(" ", "_").replace("/", "_") + ".csv"

                # 首次记录或库存变化处理
                if option_name not in prev_stock:
                    save_to_csv(csv_filename, current_time, f"初始库存: {stock}", 0)
                    prev_stock[option_name] = stock
                elif stock != prev_stock[option_name]:
                    diff = prev_stock[option_name] - stock
                    change_desc = f"{prev_stock[option_name]} -> {stock}"
                    save_to_csv(csv_filename, current_time, change_desc, diff)
                    prev_stock[option_name] = stock

        except Exception as e:
            print(f"监控循环异常: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n监控程序被用户终止")
        with lines_lock:
            pending = lines_since_last_push
        if pending > 0:
            print(f"正在推送剩余的 {pending} 条数据...")
            with file_lock:
                success = git_push_update()
            if success:
                with lines_lock:
                    lines_since_last_push = 0
                print("✅ 剩余数据已推送")
            else:
                print("⚠️ 剩余数据推送失败，请手动检查")
        else:
            print("无待推送数据")
        print("程序已退出")