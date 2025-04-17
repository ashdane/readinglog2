from flask import Flask, render_template, session, redirect, url_for, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
from sqlalchemy import text

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ReadingLog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'supersecretkey'

db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)


class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    chapter_title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(100), default="Unknown")
    translator = db.Column(db.String(100), default="")

class UserProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    page_no = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    

class BookTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    book_title = db.Column(db.String(100), nullable=False)
    tag = db.Column(db.String(50), nullable=False)


def init_db_metadata():
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(book)"))
            columns = [row[1] for row in result.fetchall()]
            

            if 'author' not in columns:
                conn.execute(text("ALTER TABLE book ADD COLUMN author VARCHAR(100) DEFAULT 'Unknown'"))
                print("Added author column to Book table")

            if 'translator' not in columns:
                conn.execute(text("ALTER TABLE book ADD COLUMN translator VARCHAR(100) DEFAULT ''"))
                print("Added translator column to Book table")
            
            conn.commit()
    except Exception as e:
        print(f"Error checking/updating columns: {e}")
    

    existing_books = Book.query.filter(Book.author != 'Unknown').first()
    
    if existing_books is None:
        aesop_books = Book.query.filter_by(title="Aesops-Fables").all()
        for book in aesop_books:
            book.author = "B.B. Gallagher"
            book.translator = ""

        panchatantra_books = Book.query.filter_by(title="Panchatantra").all()
        for book in panchatantra_books:
            book.author = "Vishnu Sharma"
            book.translator = "Arthur William Ryder"

        if BookTag.query.filter_by(book_title="Aesops-Fables").first() is None:
            aesop_tags = [
                BookTag(book_title="Aesops-Fables", tag="Fables"),
                BookTag(book_title="Aesops-Fables", tag="Morals"),
                BookTag(book_title="Aesops-Fables", tag="Animals"),
                BookTag(book_title="Aesops-Fables", tag="Wisdom"),
                BookTag(book_title="Aesops-Fables", tag="Greek")
            ]
            for tag in aesop_tags:
                db.session.add(tag)

            panchatantra_tags = [
                BookTag(book_title="Panchatantra", tag="Indian"),
                BookTag(book_title="Panchatantra", tag="Wisdom"),
                BookTag(book_title="Panchatantra", tag="Animals"),
                BookTag(book_title="Panchatantra", tag="Morals"),
                BookTag(book_title="Panchatantra", tag="Sanskrit")
            ]
            for tag in panchatantra_tags:
                db.session.add(tag)
        
        db.session.commit()
        print("Book info added to database.")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session['username'] = username
            return redirect(url_for('select_book'))
        else:
            return render_template('login.html', error="Invalid username or password. Please try again.")

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    title = request.args.get('title')
    if not username or not title:
        return redirect(url_for('select_book'))

    user = User.query.filter_by(username=username).first()
    if not user:
        return redirect(url_for('index'))

    pages = Book.query.filter_by(title=title).all()
    total_pages = len(pages)

    read_progress = UserProgress.query.join(Book).filter(
        UserProgress.user_id == user.id,
        Book.title == title
    ).order_by(UserProgress.timestamp).all()

    pages_read = len(read_progress)
    pages_left = total_pages - pages_read

    last_read = read_progress[-1] if read_progress else None
    last_read_page = last_read.page_no if last_read else pages[0].id if pages else 1

    sessions = {}
    for progress in read_progress:
        session_id = str(progress.timestamp.date()) + " " + str(progress.timestamp.hour) + ":" + str(progress.timestamp.minute)
        if session_id not in sessions:
            sessions[session_id] = []
        sessions[session_id].append(progress.timestamp)

    session_labels = list(sessions.keys())
    pages_per_session = [len(sessions[s]) for s in session_labels]
    
    avg_pages_per_session = round(sum(pages_per_session) / len(pages_per_session), 1) if pages_per_session else 0

    def make_chart(fig_func):
        fig, ax = plt.subplots()
        fig_func(ax)
        img = io.BytesIO()
        plt.tight_layout()
        plt.savefig(img, format='png')
        img.seek(0)
        plt.close()
        return base64.b64encode(img.getvalue()).decode()

    bar_chart = make_chart(lambda ax: (ax.bar(session_labels, pages_per_session), ax.set(title='Pages Read Per Session', xlabel='Session', ylabel='Pages Read')))
    line_chart = make_chart(lambda ax: (ax.plot(session_labels, pages_per_session, marker='o', linestyle='-', color='b'), ax.set(title='Reading Trend Over Time', xlabel='Session', ylabel='Pages Read')))
    pie_chart = make_chart(lambda ax: ax.pie([pages_read, pages_left], labels=['Read', 'Unread'], autopct='%1.1f%%'))

    streak_dates = sorted({p.timestamp.date() for p in read_progress})
    streak = max_streak = 1
    for i in range(1, len(streak_dates)):
        if (streak_dates[i] - streak_dates[i-1]).days == 1:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 1

    streak_chart = make_chart(lambda ax: (ax.bar(['Max Streak'], [max_streak]), ax.set_title('Max Reading Streak (Days)')))

    hourly_counts = {}
    for p in read_progress:
        hour = p.timestamp.hour
        hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

    speed_chart = make_chart(lambda ax: (ax.bar(list(hourly_counts.keys()), list(hourly_counts.values())), ax.set(title='Pages Read by Hour', xlabel='Hour of Day', ylabel='Pages Read')))

    cumulative = list(range(1, pages_read + 1))
    cumulative_chart = make_chart(lambda ax: (ax.plot(list(range(1, pages_read + 1)), cumulative), ax.set(title='Cumulative Reading Progress', xlabel='Page Count', ylabel='Total Pages Read')))

    week_counts = {}
    for p in read_progress:
        week = p.timestamp.strftime("%Y-W%U")
        week_counts[week] = week_counts.get(week, 0) + 1

    weekly_chart = make_chart(lambda ax: (ax.bar(list(week_counts.keys()), list(week_counts.values())), ax.set(title='Weekly Reading Comparison', xlabel='Week', ylabel='Pages Read'), ax.tick_params(axis='x', rotation=45)))

    return render_template('dashboard.html',
                           total_pages=total_pages,
                           pages_read=pages_read,
                           pages_left=pages_left,
                           bar_chart=bar_chart,
                           line_chart=line_chart,
                           pie_chart=pie_chart,
                           streak_chart=streak_chart,
                           speed_chart=speed_chart,
                           cumulative_chart=cumulative_chart,
                           weekly_chart=weekly_chart,
                           last_read_page=last_read_page,
                           avg_pages_per_session=avg_pages_per_session,
                           title=title)

@app.route('/read/<int:page_no>')
def read(page_no):
    page = Book.query.get_or_404(page_no)

    username = session.get('username', 'guest')
    user = User.query.filter_by(username=username).first()

    if user:
        already_read = UserProgress.query.filter_by(user_id=user.id, page_no=page_no).first()

        if not already_read:
            progress = UserProgress(
                user_id=user.id,
                book_id=page.id,
                page_no=page_no,
                timestamp=datetime.utcnow()
            )
            db.session.add(progress)
            db.session.commit()

    next_page = Book.query.filter_by(title=page.title, id=page_no + 1).first()
    previous_page = Book.query.filter_by(title=page.title, id=page_no - 1).first()

    return render_template('read.html', page=page,
                           next_page=next_page.id if next_page else None,
                           previous_page=previous_page.id if previous_page else None)

@app.route('/reset')
def reset_progress():
    username = session.get('username')
    if not username:
        return redirect(url_for('index'))

    user = User.query.filter_by(username=username).first()
    if user:
        UserProgress.query.filter_by(user_id=user.id).delete()
        db.session.commit()

    current_title = request.args.get('title')
    
    if current_title:
        return redirect(url_for('dashboard', title=current_title))
    
    return redirect(url_for('select_book'))
  
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template('signup.html', error="Username already exists. Please choose a different username.")

        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()

        session['username'] = username
        return redirect(url_for('select_book'))

    return render_template('signup.html')

 
@app.route('/select_book')
def select_book():
    username = session.get('username')
    if not username:
        return redirect(url_for('index'))


    search_query = request.args.get('search', '').strip().lower()
    

    if not search_query:
        book_data = db.session.query(
            Book.title, Book.author, Book.translator
        ).distinct().all()
        
 
        books_data = {}
        for book in book_data:
            if book.title not in books_data:
                tags = [tag.tag for tag in BookTag.query.filter_by(book_title=book.title).all()]
                
                books_data[book.title] = {
                    'author': book.author or 'Unknown',
                    'translator': book.translator or '',
                    'tags': tags
                }
        
        return render_template('select_book.html', books_data=books_data, search_query='')
    
    title_matches = db.session.query(Book.title, Book.author, Book.translator).filter(
        db.or_(
            Book.title.ilike(f'%{search_query}%'),
            Book.author.ilike(f'%{search_query}%'),
            Book.translator.ilike(f'%{search_query}%'),
            Book.content.ilike(f'%{search_query}%')
        )
    ).distinct().all()
    

    tag_matches = db.session.query(BookTag.book_title).filter(
        BookTag.tag.ilike(f'%{search_query}%')
    ).distinct().all()

    matching_titles = set([book.title for book in title_matches])
    for tag in tag_matches:
        matching_titles.add(tag.book_title)
    

    books_data = {}
    for title in matching_titles:
        book = db.session.query(Book.author, Book.translator).filter_by(title=title).first()
        tags = [tag.tag for tag in BookTag.query.filter_by(book_title=title).all()]
        
        books_data[title] = {
            'author': book.author if book else 'Unknown',
            'translator': book.translator if book and book.translator else '',
            'tags': tags
        }
    
    return render_template('select_book.html', books_data=books_data, search_query=search_query)

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('settings_context', None)
    return redirect(url_for('index'))


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    username = session.get('username')
    if not username:
        return redirect(url_for('index'))

    user = User.query.filter_by(username=username).first()
    if not user:
        return redirect(url_for('index'))

    referrer = request.referrer
    
    if not referrer or 'settings' in referrer:
        referrer = session.get('settings_context', url_for('select_book'))
    elif 'dashboard' in referrer or 'read' in referrer or 'select_book' in referrer:
        session['settings_context'] = referrer

    if request.method == 'POST':
        if 'change_password' in request.form:
            current_password = request.form['password']
            new_password = request.form['new_password']
            confirm_password = request.form['confirm_password']

            if user.password != current_password:
                return render_template('settings.html', error="Incorrect current password.", referrer=referrer)

            if new_password != confirm_password:
                return render_template('settings.html', error="New password and confirmation do not match.", referrer=referrer)

            user.password = new_password
            db.session.commit()

            return render_template('settings.html', message="Password updated successfully.", referrer=referrer)

        elif 'delete_profile' in request.form:
            password = request.form['password']
            
            if user.password != password:
                return render_template('settings.html', error="Incorrect password. Account deletion failed.", referrer=referrer)
            
            UserProgress.query.filter_by(user_id=user.id).delete()
            db.session.delete(user)
            db.session.commit()

            session.pop('username', None)
            session.pop('settings_context', None)
            return redirect(url_for('index'))

    return render_template('settings.html', referrer=referrer)

with app.app_context():
    db.create_all()
    init_db_metadata()

if __name__ == '__main__':
    app.run(debug=True)
