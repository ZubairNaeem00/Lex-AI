# LexAI — AI Legal Agent for Pakistan
### React + Tailwind CSS + React Router Frontend

---

## 📁 Project Structure

```
lexai/
├── public/
│   └── index.html
├── src/
│   ├── components/
│   │   ├── UI.jsx              # Shared: GoldButton, Card, Input, Badge, etc.
│   │   ├── Navbar.jsx          # Top navigation (React Router NavLinks)
│   │   ├── Sidebar.jsx         # Left sidebar for dashboard pages
│   │   └── DashboardLayout.jsx # Layout wrapper (Sidebar + <Outlet />)
│   ├── pages/
│   │   ├── LandingPage.jsx     # Route: /
│   │   ├── LoginPage.jsx       # Route: /login
│   │   ├── SignupPage.jsx      # Route: /signup  (3-step wizard)
│   │   ├── DashboardPage.jsx   # Route: /dashboard
│   │   ├── UploadPage.jsx      # Route: /upload
│   │   ├── ChatPage.jsx        # Route: /chat
│   │   └── ReportsPage.jsx     # Route: /reports
│   ├── App.js                  # React Router config
│   ├── index.js                # Entry point
│   └── index.css               # Tailwind directives + global styles
├── tailwind.config.js          # Custom tokens (navy, gold, cream, etc.)
├── postcss.config.js
└── package.json
```

---

## 🚀 Setup

```bash
# 1. Install dependencies
npm install

# 2. Start dev server
npm start

# 3. Open http://localhost:3000
```

---

## 🎨 Design Tokens (tailwind.config.js)

| Token         | Value       | Usage                     |
|---------------|-------------|---------------------------|
| `navy`        | `#08101f`   | Page background           |
| `navy-2/3/4`  | dark blues  | Cards, sidebars           |
| `gold`        | `#c8a84b`   | Primary accent, CTAs      |
| `gold-light`  | `#e4c97a`   | Hover states              |
| `cream`       | `#f0ead8`   | Body text                 |
| `cream-dim`   | `#9e9280`   | Secondary text            |
| `jade`        | `#3fb27f`   | Success / active status   |
| `crimson`     | `#c94a4a`   | Error / danger            |

---

## 🗺️ Routes

| Path         | Page                     | Layout          |
|--------------|--------------------------|-----------------|
| `/`          | Landing Page             | Navbar only     |
| `/login`     | Login                    | No navbar       |
| `/signup`    | Sign Up (3-step wizard)  | No navbar       |
| `/dashboard` | Dashboard Home           | Navbar + Sidebar|
| `/upload`    | Document Upload/Analysis | Navbar + Sidebar|
| `/chat`      | AI Chat Interface        | Navbar + Sidebar|
| `/reports`   | Reports & Drafts         | Navbar + Sidebar|

---

## 🔌 Connecting to Backend

Replace the mock timeouts in each page with real API calls:

```js
// Example: in LoginPage.jsx
const response = await fetch('/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password }),
});
const data = await response.json();
if (data.token) navigate('/dashboard');
```

Key endpoints to wire up:
- `POST /api/auth/login`
- `POST /api/auth/signup`
- `POST /api/documents/upload`
- `POST /api/chat/message`
- `GET  /api/reports`
- `POST /api/reports/generate`
