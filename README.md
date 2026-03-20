# School ERP Backend

Production-grade modular Flask backend with RBAC.

## 🚀 Quick Start

```bash
# 1. Initialize database
python -c "from backend.app import create_app; app = create_app(); app.app_context().push(); from backend.core.database import db; db.create_all()"

# 2. Seed RBAC system
python -m backend.scripts.seed_rbac

# 3. Create admin user
python -m backend.scripts.create_admin

# 4. Run server
python backend/app.py
```

Server: `http://0.0.0.0:5001`

## Docker (full stack)

From the **repository root** (parent of `app/`), PostgreSQL, Redis, this API, Celery, school admin web, and super admin panel can run with Compose. The image installs WeasyPrint’s system libraries for you.

```bash
cp docker/env/local.env.example docker/env/local.env && make docker-local
# Production-style: copy docker/env/production.env.example → docker/env/production.env, then make docker-production
```

Details, mobile (Expo) notes, and production hints: [docker/README.md](../../docker/README.md).

## PDF generation (WeasyPrint)

Fee/finance PDFs use **WeasyPrint**, which needs **Pango and related native libraries** on the machine (in addition to `pip install -r requirements.txt` from `app/`).

**Do not use `apt` on macOS** — that is for Debian/Ubuntu only. On a Mac, use Homebrew (below).

**macOS (Homebrew)**

```bash
brew install weasyprint
```

Then confirm Python sees Pango (from your `app/` venv):

```bash
python -c "from weasyprint import HTML; print('ok')"
```

If you use **Conda** `base` together with a project venv, linking can get confused; prefer activating only the project venv, or install via `conda install -c conda-forge weasyprint` into the environment that runs the app.

**macOS: `brew install weasyprint` says OK, but Python still errors on Pango**

Homebrew puts `.dylib` files under `$(brew --prefix)/lib`. Your **pip-installed** WeasyPrint runs inside **Python**, which may not search there—especially if **Conda** has changed library paths.

1. Drop Conda for this shell, keep only the project venv, then test:

   ```bash
   conda deactivate   # repeat until `(base)` is gone from the prompt
   cd app && source venv/bin/activate
   python -c "from weasyprint import HTML; print('ok')"
   ```

2. If it still fails, point the dynamic loader at Homebrew’s libs for this terminal session (Apple Silicon: prefix is usually `/opt/homebrew`; Intel: `/usr/local`):

   ```bash
   export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
   python -c "from weasyprint import HTML; print('ok')"
   ```

3. Or avoid the Homebrew-vs-pip split: install the library into the same Conda env you run the app from: `conda install -c conda-forge weasyprint`, and use that env’s Python (not a mixed venv+base setup).

**Linux — Debian / Ubuntu** (typical production image; use when WeasyPrint is installed in a **venv** and wheels are used)

```bash
sudo apt install python3-pip libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0 libharfbuzz-subset0
```

On minimal images, if `pip` fails to build or load the extension, add dev headers per [WeasyPrint — First steps](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html):

```bash
sudo apt install libffi-dev libjpeg-dev libopenjp2-7-dev
```

## 📁 Structure

```
backend/
├── app.py              # Application factory (RUN THIS)
├── config/             # Configuration
├── core/               # Infrastructure
│   ├── database.py
│   └── decorators/     # @auth_required, @require_permission
├── modules/            # Business modules
│   ├── auth/          # Authentication
│   ├── rbac/          # Roles & permissions
│   ├── users/         # User management
│   └── mailer/        # Email service
├── shared/            # Utilities
└── scripts/           # Admin scripts
```

## 📚 Documentation

- **`../REFACTORING_SUMMARY.md`** - Overview and quick reference
- **`../QUICK_START.md`** - Setup and common tasks
- **`../BACKEND_ARCHITECTURE_REFACTORING.md`** - Complete documentation

## 🔧 Key Concepts

### Decorators
```python
from backend.core.decorators import auth_required, require_permission

@bp.route('/endpoint')
@auth_required
@require_permission('resource.action')
def endpoint():
    # g.current_user available
    pass
```

### Service Pattern
```python
# services.py - Business logic
def create_item(data):
    return {'success': True, 'item': item}

# routes.py - HTTP handling
@bp.route('/items', methods=['POST'])
@auth_required
@require_permission('item.create')
def create_item_route():
    result = create_item(request.get_json())
    return success_response(result['item'], 201)
```

## 🎯 RBAC

**Philosophy:**
- Authorization via permissions only
- Role names never in business logic
- Permission naming: `resource.action.scope`
- `manage` implies all actions

**Example:**
```python
from backend.modules.rbac.services import has_permission

if has_permission(user_id, 'student.create'):
    # Authorized
    pass
```

## 📡 API Endpoints

- `/api/auth` - Authentication
- `/api/rbac` - RBAC management
- `/api/users` - User management
- `/api/health` - Health check

## ⚡ Scripts

```bash
# Seed RBAC
python -m backend.scripts.seed_rbac

# Create admin
python -m backend.scripts.create_admin

# RBAC helpers (Flask shell)
from backend.scripts.rbac_helpers import *
assign_admin_role('admin@school.com')
```

## ✨ Features

- ✅ Application factory pattern
- ✅ Modular architecture
- ✅ Permission-based RBAC
- ✅ JWT authentication
- ✅ Email service
- ✅ Health checks
- ✅ Error handling

## 🔄 Add New Module

```bash
mkdir -p backend/modules/new_module
cd backend/modules/new_module

# Create files
touch __init__.py models.py routes.py services.py
```

Then register in `app.py`:
```python
from backend.modules.new_module import new_module_bp
app.register_blueprint(new_module_bp, url_prefix='/api/new-module')
```

## 📞 Support

Check the main documentation files in the project root for detailed guides.

**Happy coding! 🎉**
