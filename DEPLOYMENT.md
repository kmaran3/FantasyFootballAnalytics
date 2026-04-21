# Railway Deployment Guide

## 📦 **Deploy to Railway**

### 1️⃣ **Push Your Code to GitHub**

All deployment files are ready! Push to GitHub:

```bash
git add .
git commit -m "Add Railway deployment configuration"
git push origin main
```

### 2️⃣ **Create Railway Account**

1. Go to [railway.app](https://railway.app)
2. Sign up/Login with GitHub
3. Authorize Railway to access your repositories

### 3️⃣ **Deploy Your Project**

1. Click **"New Project"**
2. Select **"Deploy from GitHub repo"**
3. Choose **`kmaran3/StepByStepToolKit`** repository
4. Railway will automatically:
   - Detect Python/Flask
   - Install dependencies from `requirements.txt`
   - Run the `Procfile` command (`gunicorn app:app`)
   - Assign a temporary URL (e.g., `yourapp.up.railway.app`)

### 4️⃣ **Set Environment Variables** (Optional)

In Railway dashboard → Your Project → Variables:
- `FLASK_ENV=production`
- `SECRET_KEY=your-secret-key-here` (if needed)

### 5️⃣ **Add Custom Domain**

#### **Option A: Buy Domain through Railway**
1. Go to Project Settings → Domains
2. Click **"Custom Domain"**
3. Purchase domain directly through Railway

#### **Option B: Use Your Own Domain**
1. Buy domain from Namecheap, GoDaddy, etc.
2. In Railway: Settings → Domains → Add Custom Domain
3. Enter your domain (e.g., `fantasyfootball.com`)
4. Railway will provide DNS records:
   - **CNAME**: Point `www` to Railway URL
   - **A Record**: Point `@` to Railway IP
5. Add these records in your domain registrar's DNS settings
6. Wait 5-60 minutes for DNS propagation

### 6️⃣ **Popular Domain Registrars**

- **Namecheap**: ~$10/year (.com)
- **GoDaddy**: ~$12/year (.com)
- **Google Domains**: ~$12/year (.com)
- **Cloudflare**: ~$9/year (.com) + free CDN

### 7️⃣ **Verify Deployment**

Once deployed, visit:
- Railway URL: `https://yourapp.up.railway.app`
- Custom domain: `https://yourdomain.com`

Test all pages:
- Rankings: `/rankings/ppr`
- Player profiles
- About page
- Contact page

## 🎯 **What's Included**

✅ `Procfile` - Railway startup command  
✅ `railway.toml` - Railway configuration  
✅ `requirements.txt` - Updated with gunicorn  
✅ `app.py` - Production-ready with PORT handling  
✅ `.gitignore` - Clean repo (no cache/test files)

## 💰 **Pricing**

- **Railway Free Tier**: 500 hours/month, $5 credit
- **Pro Plan**: $5/month, 500 hours + $0.000231/min after
- **Domain**: $9-15/year (separate from Railway)

## 🚀 **Quick Deploy Command**

```bash
git add .
git commit -m "Add Railway deployment configuration"
git push origin main
```

Then go to Railway dashboard and click deploy!

---

**Need help?** Check [Railway Docs](https://docs.railway.app) or [Discord](https://discord.gg/railway)
