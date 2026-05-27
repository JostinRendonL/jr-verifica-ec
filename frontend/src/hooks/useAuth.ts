import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { MeResponse } from '@/types'

export function useAuth() {
  const { data, isLoading } = useQuery<MeResponse>({
    queryKey: ['me'],
    queryFn: async () => {
      const res = await api.get<MeResponse>('/me')
      return res.data
    },
    retry: false,
    staleTime: 1000 * 60 * 5, // 5 min
  })

  return {
    usuario: data,
    autenticado: data?.autenticado ?? false,
    isLoading,
  }
}
