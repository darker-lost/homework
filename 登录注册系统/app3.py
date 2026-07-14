# ============================================================
# Flask 登录注册系统
# 技术栈：Flask + PyMySQL + Werkzeug
# 功能：用户注册、用户登录、登录后主页、退出登录
# ============================================================

# 从 flask 包导入需要的功能
# Flask：创建 Web 应用的核心类
# render_template：渲染 HTML 模板
# request：获取浏览器提交的请求数据（如表单）
# redirect, url_for：实现页面重定向
# session：保存用户登录状态（基于 Cookie）
# flash：向后端模板一次性发送提示消息
from flask import Flask, render_template, request, redirect, url_for, session, flash
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from contextlib import contextmanager
from functools import wraps
import os
import re

# ------------------------------------------------------------
# 1. 创建 Flask 应用
# ------------------------------------------------------------
app = Flask(__name__)

# ------------------------------------------------------------
# 2. Session 密钥
# ------------------------------------------------------------
# 强制从环境变量读取，避免使用硬编码弱密钥
app.secret_key = os.environ.get('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError(
        "SECRET_KEY environment variable is required. "
        "Example: export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32)')"
    )

# ------------------------------------------------------------
# 3. 数据库连接配置
# ------------------------------------------------------------
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'root'),
    'database': os.environ.get('DB_NAME', 'root'),
    'port': int(os.environ.get('DB_PORT', 3306)),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


@contextmanager
def get_db():
    """获取数据库连接（上下文管理器，自动关闭）"""
    conn = None
    try:
        conn = pymysql.connect(**DB_CONFIG)
        yield conn
    finally:
        if conn is not None:
            conn.close()


def init_db():
    """初始化数据库表（无需外部 sql 文件）"""
    with get_db() as db:
        with db.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    email VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        db.commit()
    print("[DB] 用户表已就绪")


def login_required(f):
    """登录校验装饰器：未登录则重定向到登录页"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ------------------------------------------------------------
# 4. 根路由
# ------------------------------------------------------------
@app.route('/')
def index():
    """网站首页，默认重定向到登录页"""
    return redirect(url_for('login'))

# 启动时自动建表
init_db()


# ------------------------------------------------------------
# 5. 登录
# ------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('请先登录', 'error')
            return render_template('login.html')

        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT id, username, password, email FROM users WHERE username = %s",
                    (username,)
                )
                user = cursor.fetchone()

                if not user:
                    flash('账户不存在', 'error')
                    return render_template('login.html')

                if not check_password_hash(user['password'], password):
                    flash('密码错误', 'error')
                    return render_template('login.html')

                session['user_id'] = user['id']
                session['username'] = user['username']
                session['email'] = user['email']

                return redirect(url_for('dashboard'))

    # GET 请求直接返回登录页面
    return render_template('login.html')


# ------------------------------------------------------------
# 6. 注册
# ------------------------------------------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not username or not email or not password:
            flash('请填写完整信息', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('两次输入的密码不一致', 'error')
            return render_template('register.html')

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            flash('邮箱格式不正确', 'error')
            return render_template('register.html')

        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE username = %s OR email = %s",
                    (username, email)
                )
                if cursor.fetchone():
                    flash('用户名或邮箱已被注册', 'error')
                    return render_template('register.html')

                # 使用 OWASP 推荐的 pbkdf2:sha256:600000 迭代次数
                hashed_password = generate_password_hash(password, method='pbkdf2:sha256:600000')
                cursor.execute(
                    "INSERT INTO users (username, password, email) VALUES (%s, %s, %s)",
                    (username, hashed_password, email)
                )
                db.commit()
                flash('注册成功，请登录', 'success')
                return redirect(url_for('login'))

    # GET 请求返回注册页面
    return render_template('register.html')


# ------------------------------------------------------------
# 7. 主页（需登录）
# ------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    """登录后的主页"""
    return render_template(
        'dashboard.html',
        username=session['username'],
        email=session['email']
    )


# ------------------------------------------------------------
# 8. 退出
# ------------------------------------------------------------
@app.route('/logout')
def logout():
    """退出登录"""
    session.clear()
    return redirect(url_for('login'))


# ------------------------------------------------------------
# 9. 入口
# ------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
