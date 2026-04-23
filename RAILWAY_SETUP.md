# Railway Deployment Guide

## 🚂 Required Environment Variables

Set these in your Railway dashboard (Settings > Variables):

### Required:
- `SECRET_KEY` - Generate with: `python -c "import os; print(os.urandom(32).hex())"`
- `FLASK_ENV=production`
- `PORT` - Railway sets this automatically (default: 5001)

### Optional:
- `DATABASE_URL` - Railway provides this if using PostgreSQL addon
  - If not set, defaults to SQLite (not recommended for production)

## 📝 Deployment Steps

1. **Connect Repository to Railway**
   - Go to Railway dashboard
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose your repository

2. **Set Environment Variables**
   ```bash
   # Generate a secure SECRET_KEY
   python -c "import os; print(os.urandom(32).hex())"
   
   # Add to Railway:
   SECRET_KEY=<generated-key>
   FLASK_ENV=production
   ```

3. **Deploy**
   - Railway will automatically detect Python and use the Procfile
   - It will install dependencies from requirements.txt
   - The app will start using gunicorn

## 🔧 Configuration Files

- **Procfile**: `web: gunicorn app:app`
- **railway.toml**: Contains deployment settings
- **runtime.txt**: Specifies Python version

## 🗄️ Database Setup

### Using SQLite (Default):
- Database persists in the `/app/instance` volume
- Configured in railway.toml

### Using PostgreSQL (Recommended):
1. Add PostgreSQL addon in Railway
2. Railway automatically sets `DATABASE_URL`
3. No code changes needed!

## ✅ Verify Deployment

After deployment:
1. Visit your Railway URL
2. Should see the login page
3. Register a new account (password requirements enforced)
4. Test login functionality

## 🔒 Security Checklist

- [x] SECRET_KEY from environment variable
- [x] Password hashing enabled
- [x] Secure session cookies
- [x] Environment-based configuration
- [ ] HTTPS enabled (Railway provides this automatically)
- [ ] Database backups configured

## 🐛 Troubleshooting

### App won't start:
- Check Railway logs
- Verify SECRET_KEY is set
- Ensure all requirements installed

### Database errors:
- Check volume is mounted (`/app/instance`)
- Verify database file permissions

### Login issues:
- Migrate existing passwords if upgrading
- Check SECRET_KEY hasn't changed
- Clear browser cookies and retry
