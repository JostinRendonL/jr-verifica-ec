import axios from 'axios'

const api = axios.create({
  // En dev el proxy de Vite redirige al FastAPI.
  // En producción FastAPI sirve el build desde /static/frontend.
  baseURL: '/',
  withCredentials: true, // necesario para la cookie jr_session
  headers: { 'Content-Type': 'application/json' },
})

// Si el backend devuelve 401, redirigir al login
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api
