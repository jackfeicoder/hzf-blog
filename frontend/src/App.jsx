import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import PostPage from './pages/PostPage'
import Editor from './pages/Editor'
import Login from './pages/Login'
import Register from './pages/Register'
import Profile from './pages/Profile'
import Rank from './pages/Rank'
import ChatAI from './pages/ChatAI'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/post/:id" element={<PostPage />} />
            <Route path="/write" element={<Editor />} />
            <Route path="/edit/:id" element={<Editor />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/u/:username" element={<Profile />} />
            <Route path="/rank" element={<Rank />} />
            <Route path="/ai" element={<ChatAI />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </AuthProvider>
  )
}
