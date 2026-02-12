import { create } from 'zustand'
import type { InventoryType } from '@/types'

interface InventoryState {
  types: InventoryType[]
  setTypes: (types: InventoryType[]) => void
}

export const useInventoryStore = create<InventoryState>()((set) => ({
  types: [],
  setTypes: (types) => set({ types }),
}))
