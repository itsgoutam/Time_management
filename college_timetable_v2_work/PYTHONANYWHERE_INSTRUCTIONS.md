# Deploying to PythonAnywhere

Follow these step-by-step instructions to get your EduScheduler Django application running on a free PythonAnywhere account.

## Step 1: Create a PythonAnywhere Account
1. Go to [pythonanywhere.com](https://www.pythonanywhere.com/) and click **Pricing & signup**.
2. Select the **Create a Beginner account** (free tier).
3. Choose a username (this will be your domain name, e.g., `username.pythonanywhere.com`).

## Step 2: Upload Your Code
1. Once logged in, go to the **Files** tab.
2. Under "Directories", type `mysite` and click **New directory**.
3. Now upload your project files. You can upload the `.zip` of your code, or upload files one by one. If you use a `.zip`, open a **Bash** console (from the Consoles tab) and run:
   ```bash
   unzip your_upload.zip -d mysite
   ```
   *Note: Ensure `manage.py` is directly inside `/home/yourusername/mysite/`.*

## Step 3: Create a Virtual Environment and Install Dependencies
1. Go to the **Consoles** tab and start a new **Bash** console.
2. Run the following commands to create a virtual environment and install the required packages:
   ```bash
   mkvirtualenv --python=python3.10 myenv
   cd ~/mysite
   pip install -r requirements.txt
   ```
3. Run migrations and collect static files so your CSS/Images work:
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

## Step 4: Configure the Web App
1. Go to the **Web** tab and click **Add a new web app**.
2. **Domain name:** Click Next (it will use your free username domain).
3. **Framework:** Choose **Manual configuration** (do *not* choose Django).
4. **Python version:** Choose **Python 3.10** (matching what we used for the virtualenv).
5. Click Next to finish the wizard.

## Step 5: Configure Paths & WSGI
Now you're on your Web app dashboard. Scroll down and fill in the following sections:

**Virtualenv:**
- Enter `/home/yourusername/.virtualenvs/myenv` (replace `yourusername` with your actual PythonAnywhere username).

**Code:**
- **Source code:** `/home/yourusername/mysite`
- **Working directory:** `/home/yourusername/mysite`

**Static files:**
- Click **Enter path** and add:
  - **URL:** `/static/`
  - **Directory:** `/home/yourusername/mysite/staticfiles`

**WSGI Configuration File:**
- Click the link under "WSGI configuration file" (it looks like `/var/www/yourusername_pythonanywhere_com_wsgi.py`).
- Delete all the default code in that file.
- Paste the following exactly (make sure to replace `yourusername`!):

```python
import os
import sys

# Add your project directory to the sys.path
path = '/home/yourusername/mysite'
if path not in sys.path:
    sys.path.append(path)

# Set environment variable to tell django where your settings module is
os.environ['DJANGO_SETTINGS_MODULE'] = 'college_timetable.settings'

# Serve django
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```
- Click **Save** in the top right, then go back to the Web tab.

## Step 6: Reload and Visit!
1. At the top of the **Web** tab, click the big green **Reload yourusername.pythonanywhere.com** button.
2. Click your domain link at the top of the page.
3. Your app should now be live! Log in with `admin` / `admin123`.

### Troubleshooting
If you see a "Something went wrong" error page:
1. Go to the **Web** tab and scroll down to the **Log files** section.
2. Click on the **Error log** link to see exactly what caused the crash.
