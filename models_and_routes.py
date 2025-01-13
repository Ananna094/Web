from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from functools import wraps
import jwt
from sqlalchemy import or_

# Initialize blueprints
user_blueprint = Blueprint('users', __name__)
video_blueprint = Blueprint('videos', __name__)

# JWT decorator for authentication
def authenticate(app_config):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = request.headers.get('Authorization', '').split(" ")[-1]
            if not token:
                return jsonify({'error': 'Access token missing'}), 401
            try:
                decoded_token = jwt.decode(token, app_config['SECRET_KEY'], algorithms=["HS256"])
                current_user = decoded_token['user']
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Access token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid access token'}), 401
            return f(current_user, *args, **kwargs)
        return wrapper
    return decorator

# Models
def init_models(db):
    class User(db.Model):
        __tablename__ = 'Users'
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(50), unique=True, nullable=False)
        password_hash = db.Column(db.String(255), nullable=False)
        role = db.Column(db.String(20), nullable=False)
        email = db.Column(db.String(255), unique=True, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow)
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class Video(db.Model):
        __tablename__ = 'Videos'
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(255), nullable=False)
        description = db.Column(db.Text)
        creator_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
        file_url = db.Column(db.String(2083), nullable=False)
        upload_date = db.Column(db.DateTime, default=datetime.utcnow)
        hashtags = db.Column(db.String(255))
        updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    class Comment(db.Model):
        __tablename__ = 'Comments'
        id = db.Column(db.Integer, primary_key=True)
        video_id = db.Column(db.Integer, db.ForeignKey('Videos.id'), nullable=False)
        user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
        content = db.Column(db.Text, nullable=False)
        timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    return User, Video, Comment

# Register routes
def register_routes(app_config, db, bcrypt, blob_service, blob_container_name):
    User, Video, Comment = init_models(db)

    @user_blueprint.route('/register', methods=['POST'])
    def register_user():
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        role = data.get('role', 'consumer')

        if not username or not email or not password:
            return jsonify({'error': 'All fields are required'}), 400

        if role not in ['creator', 'consumer', 'admin']:
            return jsonify({'error': 'Invalid role provided'}), 400

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        try:
            new_user = User(username=username, email=email, password_hash=hashed_password, role=role)
            db.session.add(new_user)
            db.session.commit()
            return jsonify({'message': 'User registered successfully'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @video_blueprint.route('/upload', methods=['POST'])
    @authenticate(app_config)
    def upload_video(current_user):
        if current_user['role'] != 'creator':
            return jsonify({'error': 'Permission denied. Only creators can upload videos.'}), 403

        try:
            title = request.form.get('title')
            description = request.form.get('description', '')
            file = request.files.get('file')

            if not file:
                return jsonify({'error': 'No video file provided'}), 400

            # Save file to Azure Blob Storage
            blob_client = blob_service.get_blob_client(container=blob_container_name, blob=f"{current_user['id']}/{file.filename}")
            blob_client.upload_blob(file, overwrite=True)

            # Save video metadata to the database
            video = Video(
                title=title,
                description=description,
                creator_id=current_user['id'],
                file_url=blob_client.url
            )
            db.session.add(video)
            db.session.commit()

            return jsonify({'message': 'Video uploaded successfully', 'video_url': blob_client.url}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @video_blueprint.route('/videos', methods=['GET'])
    def get_videos():
        query = request.args.get('q', '')

        try:
            if query:
                videos = Video.query.filter(
                    or_(
                        Video.title.ilike(f"%{query}%"),
                        Video.hashtags.ilike(f"%{query}%")
                    )
                ).all()
            else:
                videos = Video.query.order_by(Video.upload_date.desc()).all()

            return jsonify([{
                'id': video.id,
                'title': video.title,
                'description': video.description,
                'file_url': video.file_url,
                'hashtags': video.hashtags
            } for video in videos]), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @video_blueprint.route('/videos/<int:video_id>/comments', methods=['POST'])
    @authenticate(app_config)
    def add_comment(current_user, video_id):
        data = request.json
        content = data.get('content')

        if not content:
            return jsonify({'error': 'Comment content is required'}), 400

        try:
            comment = Comment(video_id=video_id, user_id=current_user['id'], content=content)
            db.session.add(comment)
            db.session.commit()
            return jsonify({'message': 'Comment added successfully'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @video_blueprint.route('/videos/<int:video_id>/comments', methods=['GET'])
    def get_comments(video_id):
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        try:
            comments_query = Comment.query.filter_by(video_id=video_id).paginate(page=page, per_page=per_page)
            comments = [
                {'user_id': c.user_id, 'content': c.content, 'timestamp': c.timestamp}
                for c in comments_query.items
            ]
            return jsonify({
                'comments': comments,
                'total': comments_query.total,
                'pages': comments_query.pages,
                'current_page': comments_query.page
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def register_blueprints(app):
        app.register_blueprint(user_blueprint, url_prefix='/users')
        app.register_blueprint(video_blueprint, url_prefix='/videos')

