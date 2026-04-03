import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'https://uhnpllhudpsfsvuuzbta.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVobnBsbGh1ZHBzZnN2dXV6YnRhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUyMDUyNDEsImV4cCI6MjA5MDc4MTI0MX0.oTSSUKl8-pKx9w0Mmu_c9lFZXQHOGeGVomFdN6yP2Ys'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
