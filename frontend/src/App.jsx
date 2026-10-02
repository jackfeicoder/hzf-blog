import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './AuthContext'
import Layout from './components/Layout'
import Home from './pages/Home'
import { lazy, Suspense } from 'react'

const PostPage = lazy(() => import('./pages/PostPage'))
const Editor = lazy(() => import('./pages/Editor'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const Profile = lazy(() => import('./pages/Profile'))
const Rank = lazy(() => import('./pages/Rank'))
const ChatAI = lazy(() => import('./pages/ChatAI'))
const Visitors = lazy(() => import('./pages/Visitors'))
const Study = lazy(() => import('./pages/Study'))
const Videos = lazy(() => import('./pages/Videos'))
const Admin = lazy(() => import('./pages/Admin'))


export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Layout>
          <Suspense fallback={<div className="container empty">正在加载页面…</div>}><Routes>
            <Route path="/" element={<Home />} />
            <Route path="/post/:id" element={<PostPage />} />
            <Route path="/write" element={<Editor />} />
            <Route path="/edit/:id" element={<Editor />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/u/:username" element={<Profile />} />
            <Route path="/rank" element={<Rank />} />
            <Route path="/ai" element={<ChatAI />} />
            <Route path="/visitors" element={<Visitors />} />
            <Route path="/videos" element={<Videos />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/study" element={<Suspense fallback={<div className="container">正在加载学习打卡…</div>}><Study /></Suspense>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes></Suspense>
        </Layout>
      </BrowserRouter>
    </AuthProvider>
  )
}

