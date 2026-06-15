# app.py
import os
from datetime import datetime, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func

# 初始化应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///finance_planner.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 常量：消费板块分类
CATEGORIES = ['饮食', '交通', '学习', '娱乐', '社交', '日用品']
# 默认预算分配比例（基于可支配收入）
DEFAULT_RATIOS = {
    '饮食': 0.30,
    '交通': 0.10,
    '学习': 0.10,
    '娱乐': 0.10,
    '社交': 0.20,
    '日用品': 0.20
}

# ==================== 数据库模型 ====================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    monthly_income = db.Column(db.Float, default=0.0)      # 月收入
    savings_goal = db.Column(db.Float, default=0.0)        # 预计存钱

    budgets = db.relationship('Budget', backref='user', lazy=True, cascade='all, delete-orphan')
    expenses = db.relationship('Expense', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Budget(db.Model):
    __tablename__ = 'budgets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(20), nullable=False)   # 板块名称
    amount = db.Column(db.Float, default=0.0)             # 预算金额

    __table_args__ = (db.UniqueConstraint('user_id', 'category', name='_user_category_uc'),)

class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)
    description = db.Column(db.String(200), default='')

# ==================== 辅助函数 ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None

def get_budget_dict(user_id):
    """获取用户各板块预算的字典 {category: amount}"""
    budgets = Budget.query.filter_by(user_id=user_id).all()
    return {b.category: b.amount for b in budgets}

def get_expense_summary(user_id):
    """获取用户各板块当前总消费金额 {category: total}"""
    result = db.session.query(Expense.category, func.sum(Expense.amount).label('total'))\
                       .filter(Expense.user_id == user_id)\
                       .group_by(Expense.category).all()
    return {row.category: row.total or 0.0 for row in result}

def generate_compensation_plan(budget_dict, expense_dict, total_income, savings_goal):
    """
    根据预算和实际消费生成补偿计划文本（列表形式）
    """
    compensation = []
    over_budget_categories = []
    total_over = 0.0
    
    # 检查哪些板块超支
    for cat in CATEGORIES:
        budget = budget_dict.get(cat, 0)
        spent = expense_dict.get(cat, 0)
        if budget > 0 and spent > budget:
            over_amount = spent - budget
            total_over += over_amount
            over_budget_categories.append((cat, over_amount, spent, budget))
    
    if not over_budget_categories:
        compensation.append("✅ 恭喜！所有消费均在预算内，继续坚持良好的消费习惯吧！")
        return compensation
    
    # 总体超支建议
    compensation.append(f"⚠️ 总超支金额: {total_over:.2f} 元，需立即采取补偿措施。")
    compensation.append(f"📌 补偿建议：下月存款中扣除超支部分，或本月额外增加储蓄 {total_over:.2f} 元。")
    
    # 各板块具体补偿建议
    for cat, over_amt, spent, budget in over_budget_categories:
        if cat == '饮食':
            compensation.append(f"🍜 饮食超支 {over_amt:.2f} 元 → 建议：减少外卖/外出就餐，未来一周自制便当，预计节省 {over_amt:.2f} 元。")
        elif cat == '交通':
            compensation.append(f"🚗 交通超支 {over_amt:.2f} 元 → 建议：多用公交地铁/拼车，减少打车次数，可节省约 {over_amt:.2f} 元。")
        elif cat == '学习':
            compensation.append(f"📚 学习超支 {over_amt:.2f} 元 → 建议：优先使用免费资源（图书馆/公开课），控制购书或课程开销。")
        elif cat == '娱乐':
            compensation.append(f"🎬 娱乐超支 {over_amt:.2f} 元 → 建议：减少影院/KTV/游戏充值，选择免费休闲活动，本月剩余时间不再进行额外娱乐消费。")
        elif cat == '社交':
            compensation.append(f"👥 社交超支 {over_amt:.2f} 元 → 建议：聚餐改为AA或家中聚会，降低礼品支出，可减少约 {over_amt:.2f} 元。")
        elif cat == '日用品':
            compensation.append(f"🛒 日用品超支 {over_amt:.2f} 元 → 建议：列购物清单，避免冲动消费，优先消耗已有囤货。")
    
    # 额外整体调整建议
    compensation.append(f"💡 总超支 {total_over:.2f} 元，建议调整预算分配：暂时从娱乐/社交额度中划拨，或本月增加兼职收入。")
    return compensation

def init_default_budgets(user, disposable_income):
    """根据可支配收入按默认比例生成初始预算"""
    # 删除旧预算
    Budget.query.filter_by(user_id=user.id).delete()
    for cat in CATEGORIES:
        ratio = DEFAULT_RATIOS.get(cat, 0.1)
        amount = disposable_income * ratio
        budget = Budget(user_id=user.id, category=cat, amount=round(amount, 2))
        db.session.add(budget)
    db.session.commit()

def recalc_budgets_from_income(user, income, savings_goal):
    """根据收入和储蓄目标重新计算预算（按比例）"""
    user.monthly_income = income
    user.savings_goal = savings_goal
    disposable = income - savings_goal
    if disposable < 0:
        disposable = 0
    # 删除旧预算并按比例重建
    Budget.query.filter_by(user_id=user.id).delete()
    for cat in CATEGORIES:
        ratio = DEFAULT_RATIOS.get(cat, 0.1)
        amount = disposable * ratio
        budget = Budget(user_id=user.id, category=cat, amount=round(amount, 2))
        db.session.add(budget)
    db.session.commit()

# ==================== 路由 ====================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        
        if not username or not password:
            flash('用户名和密码不能为空', 'danger')
            return render_template('register.html')
        
        if password != confirm:
            flash('两次密码输入不一致', 'danger')
            return render_template('register.html')
        
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('用户名已存在，请更换', 'danger')
            return render_template('register.html')
        
        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('登录成功', 'success')
            # 检查是否需要初始化预算（没有预算记录）
            budget_count = Budget.query.filter_by(user_id=user.id).count()
            if budget_count == 0 and user.monthly_income > 0 and user.savings_goal >= 0:
                # 已有收入和储蓄目标，初始化预算
                disposable = user.monthly_income - user.savings_goal
                if disposable > 0:
                    init_default_budgets(user, disposable)
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    if not user:
        return redirect(url_for('logout'))
    
    # 检查用户是否已设置收入和储蓄目标
    if user.monthly_income == 0 and user.savings_goal == 0:
        # 尚未设置，跳转到预算设置页面
        flash('请先设置您的月收入与存钱目标，系统将为您自动生成消费计划。', 'info')
        return redirect(url_for('edit_budget'))
    
    # 获取预算数据
    budgets = Budget.query.filter_by(user_id=user.id).all()
    if not budgets:
        # 没有预算但已有收入，尝试初始化
        if user.monthly_income > user.savings_goal:
            disposable = user.monthly_income - user.savings_goal
            init_default_budgets(user, disposable)
            budgets = Budget.query.filter_by(user_id=user.id).all()
        else:
            flash('您的可支配收入为0或负数，请调整收入/储蓄目标', 'warning')
            return redirect(url_for('edit_budget'))
    
    budget_dict = {b.category: b.amount for b in budgets}
    expense_dict = get_expense_summary(user.id)
    
    # 计算每个板块的消费进度百分比和超支金额
    categories_data = []
    total_budget = sum(budget_dict.values())
    total_expense = sum(expense_dict.values())
    
    for cat in CATEGORIES:
        budget_amt = budget_dict.get(cat, 0)
        spent_amt = expense_dict.get(cat, 0)
        percent = (spent_amt / budget_amt * 100) if budget_amt > 0 else 0
        over = max(0, spent_amt - budget_amt)
        status = 'danger' if over > 0 else 'success'
        categories_data.append({
            'name': cat,
            'budget': budget_amt,
            'spent': spent_amt,
            'percent': min(percent, 100),
            'over': over,
            'status': status
        })
    
    # 获取最近的消费记录
    recent_expenses = Expense.query.filter_by(user_id=user.id).order_by(Expense.date.desc(), Expense.id.desc()).limit(10).all()
    
    # 生成补偿计划
    compensation_plan = generate_compensation_plan(budget_dict, expense_dict, user.monthly_income, user.savings_goal)
    
    return render_template('dashboard.html',
                           user=user,
                           categories_data=categories_data,
                           recent_expenses=recent_expenses,
                           compensation_plan=compensation_plan,
                           total_budget=total_budget,
                           total_expense=total_expense,
                           disposable_income=user.monthly_income - user.savings_goal)

@app.route('/edit_budget', methods=['GET', 'POST'])
@login_required
def edit_budget():
    user = get_current_user()
    if request.method == 'POST':
        try:
            income = float(request.form.get('monthly_income', 0))
            savings = float(request.form.get('savings_goal', 0))
            if income < 0 or savings < 0:
                flash('收入与储蓄目标不能为负数', 'danger')
                return redirect(url_for('edit_budget'))
            if income < savings:
                flash('预计存钱不能超过月收入，请调整', 'danger')
                return redirect(url_for('edit_budget'))
            
            user.monthly_income = income
            user.savings_goal = savings
            disposable = income - savings
            
            # 获取各板块自定义预算，如果没有则按默认比例
            new_budgets = {}
            for cat in CATEGORIES:
                budget_val = request.form.get(f'budget_{cat}')
                if budget_val and budget_val.strip():
                    new_budgets[cat] = round(float(budget_val), 2)
                else:
                    # 如果没有填写，则按默认比例生成
                    ratio = DEFAULT_RATIOS.get(cat, 0.1)
                    new_budgets[cat] = round(disposable * ratio, 2)
            
            # 删除旧的预算并插入新预算
            Budget.query.filter_by(user_id=user.id).delete()
            for cat, amt in new_budgets.items():
                budget = Budget(user_id=user.id, category=cat, amount=amt)
                db.session.add(budget)
            
            db.session.commit()
            flash('预算计划已成功更新！', 'success')
            return redirect(url_for('dashboard'))
        except ValueError:
            flash('请输入有效的数字金额', 'danger')
            return redirect(url_for('edit_budget'))
    
    # GET 请求: 显示当前收入和预算
    current_income = user.monthly_income or 0
    current_savings = user.savings_goal or 0
    budgets = Budget.query.filter_by(user_id=user.id).all()
    budget_dict = {b.category: b.amount for b in budgets}
    
    # 如果还没有预算，且收入和储蓄已设置，则用默认比例展示建议值
    if not budget_dict and current_income > current_savings:
        disposable = current_income - current_savings
        for cat in CATEGORIES:
            ratio = DEFAULT_RATIOS.get(cat, 0.1)
            budget_dict[cat] = round(disposable * ratio, 2)
    elif not budget_dict:
        # 无预算也无收入数据时，给个占位值
        for cat in CATEGORIES:
            budget_dict[cat] = 0.0
    
    return render_template('edit_budget.html',
                           user=user,
                           categories=CATEGORIES,
                           current_income=current_income,
                           current_savings=current_savings,
                           budget_dict=budget_dict)

@app.route('/add_expense', methods=['POST'])
@login_required
def add_expense():
    user = get_current_user()
    category = request.form.get('category')
    try:
        amount = float(request.form.get('amount', 0))
        if amount <= 0:
            flash('消费金额必须大于0', 'danger')
            return redirect(url_for('dashboard'))
        if category not in CATEGORIES:
            flash('无效的消费类别', 'danger')
            return redirect(url_for('dashboard'))
        description = request.form.get('description', '').strip()[:100]
        
        expense = Expense(user_id=user.id, category=category, amount=amount, description=description)
        db.session.add(expense)
        db.session.commit()
        flash(f'已记录 {category} 消费 {amount:.2f} 元', 'success')
    except ValueError:
        flash('金额格式错误', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/delete_expense/<int:expense_id>')
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.user_id != session['user_id']:
        abort(403)
    db.session.delete(expense)
    db.session.commit()
    flash('消费记录已删除', 'info')
    return redirect(url_for('dashboard'))

# ==================== 初始化数据库 ====================
with app.app_context():
    db.create_all()

# ==================== 主程序 ====================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)