from flask import Flask, render_template, session, redirect, url_for, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ReadingLog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'supersecretkey'  # Required for session handling

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    chapter_title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)  # 1 page per row

class UserProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    page_no = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Routes
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
            # Return with error message instead of invalid flag
            return render_template('login.html', error="Invalid username or password. Please try again.")

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    title = request.args.get('title')
    if not username or not title:
        return redirect(url_for('select_book'))  # Modified to redirect to select_book instead of itself

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
    
    # Calculate average pages per session
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

    # Get the current book title from query parameters
    current_title = request.args.get('title')
    
    # If we have a book title, redirect back to the dashboard for that book
    if current_title:
        return redirect(url_for('dashboard', title=current_title))
    
    # Otherwise, redirect to select_book
    return redirect(url_for('select_book'))
    
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check if user already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template('signup.html', error="Username already exists. Please choose a different username.")

        # Create new user
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()

        # Auto-login after signup
        session['username'] = username
        return redirect(url_for('select_book'))

    return render_template('signup.html')

# New API endpoint for search
@app.route('/api/search')
def search_books():
    search_query = request.args.get('q', '').lower()  # Convert to lowercase for case-insensitive comparison
    print(f"Search query received: '{search_query}'")
    
    # Get all unique book titles
    all_titles = [book.title for book in Book.query.with_entities(Book.title).distinct().all()]
    
    # If no search query, return all books
    if not search_query.strip():
        return jsonify({"titles": all_titles})
    
    # Initialize filtered titles list
    filtered_titles = []
    
    # First check the books table for matches in title, chapter_title, and content
    sql_filtered_books = db.session.query(Book.title).distinct().filter(
        db.or_(
            Book.title.ilike(f'%{search_query}%'),  # ilike already ignores case
            Book.chapter_title.ilike(f'%{search_query}%'),
            Book.content.ilike(f'%{search_query}%')
        )
    ).all()
    
    # Add SQL-filtered titles
    for book in sql_filtered_books:
        if book.title not in filtered_titles:
            filtered_titles.append(book.title)
    
    # Data for front-end matching of author and tags (which are in HTML, not DB)
    frontend_data = {
        "Aesop's Fables": {
            "author": "B.B. Gallagher",
            "translator": "",  # No translator for this book
            "tags": ["Fables", "Morals", "Animals", "Wisdom", "Greek"]  # Added "Greek" tag
        },
        "Panchatantra": {
            "author": "Vishnu Sharma",
            "translator": "Arthur William Ryder",
            "tags": ["Indian", "Wisdom", "Animals", "Morals", "Sanskrit"]  # Added "Sanskrit" tag
        }
    }
    
    # Additionally filter based on frontend data (authors, translators, and tags)
    for title, data in frontend_data.items():
        # Skip if already in results
        if title in filtered_titles:
            continue
            
        # Check author - case insensitive
        if search_query in data["author"].lower():
            filtered_titles.append(title)
            continue
        
        # Check translator (if any) - case insensitive
        if data["translator"] and search_query in data["translator"].lower():
            filtered_titles.append(title)
            continue
            
        # Check tags - case insensitive comparison
        for tag in data["tags"]:
            if search_query == tag.lower() or tag.lower().startswith(search_query):
                filtered_titles.append(title)
                break
    
    return jsonify({"titles": filtered_titles})
    
@app.route('/select_book')
def select_book():
    username = session.get('username')
    if not username:
        return redirect(url_for('index'))

    # Get all books to display initially
    all_books = Book.query.with_entities(Book.title).distinct().all()
    book_titles = [book.title for book in all_books]
    
    return render_template('select_book.html', all_titles=book_titles)

# Logout route
@app.route('/logout')
def logout():
    # Clear the session
    session.pop('username', None)
    return redirect(url_for('index'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    username = session.get('username')
    if not username:
        return redirect(url_for('index'))

    user = User.query.filter_by(username=username).first()
    if not user:
        return redirect(url_for('index'))

    # Get the referrer URL (where the user came from)
    referrer = request.referrer
    
    # If no referrer or it's from settings page itself, default to select_book
    if not referrer or 'settings' in referrer:
        referrer = url_for('select_book')

    if request.method == 'POST':
        # Password Change Logic
        if 'change_password' in request.form:
            current_password = request.form['password']
            new_password = request.form['new_password']
            confirm_password = request.form['confirm_password']

            # Check if the current password matches the user's existing password in the database
            if user.password != current_password:
                return render_template('settings.html', error="Incorrect current password.", referrer=referrer)

            # Check if the new password matches the confirmation password
            if new_password != confirm_password:
                return render_template('settings.html', error="New password and confirmation do not match.", referrer=referrer)

            # If everything is fine, update the password
            user.password = new_password
            db.session.commit()

            return render_template('settings.html', message="Password updated successfully.", referrer=referrer)

        # Account Deletion Logic
        elif 'delete_profile' in request.form:
            # Get password from form
            password = request.form['password']
            
            # Verify password matches the current user's password
            if user.password != password:
                return render_template('settings.html', error="Incorrect password. Account deletion failed.", referrer=referrer)
            
            # If password is correct, proceed with deletion
            # Delete associated progress data before deleting the user
            UserProgress.query.filter_by(user_id=user.id).delete()

            # Delete user record
            db.session.delete(user)
            db.session.commit()

            # Log the user out by clearing the session
            session.pop('username', None)
            return redirect(url_for('index'))

    return render_template('settings.html', referrer=referrer)

if __name__ == '__main__':
    app.run(debug=True)