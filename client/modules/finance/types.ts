/**
 * Finance module types
 */

export interface FeeComponent {
  id: string;
  fee_structure_id: string;
  name: string;
  amount: number;
  is_optional: boolean;
  sort_order: number;
}

export interface FeeStructure {
  id: string;
  academic_year_id: string;
  name: string;
  class_id: string | null;
  class_ids?: string[];
  class_name: string | null;
  due_date: string;
  created_at?: string;
  updated_at?: string;
  components: FeeComponent[];
}

export interface StudentFeeItem {
  id: string;
  student_fee_id: string;
  fee_component_id: string;
  component_name: string | null;
  amount: number;
  paid_amount: number;
}

export interface Payment {
  id: string;
  student_fee_id: string;
  amount: number;
  method: string;
  status: 'success' | 'failed' | 'refunded';
  reference_number: string | null;
  notes: string | null;
  created_at: string;
  updated_at?: string;
}

export interface StudentFee {
  id: string;
  student_id: string;
  fee_structure_id: string;
  status: 'unpaid' | 'partial' | 'paid' | 'overdue';
  total_amount: number;
  paid_amount: number;
  due_date: string;
  class_id?: string;
  academic_year_id?: string;
  student_name?: string | null;
  admission_number?: string | null;
  fee_structure_name?: string | null;
  items?: StudentFeeItem[];
  payments?: Payment[];
}

export interface CreateStructureInput {
  name: string;
  academic_year_id: string;
  due_date: string;
  components: { name: string; amount: number; is_optional: boolean }[];
  class_ids?: string[];
}

export interface UpdateStructureInput {
  name?: string;
  due_date?: string;
  class_ids?: string[];
  components?: { name: string; amount: number; is_optional: boolean }[];
}

export interface PaymentAllocation {
  item_id: string;  // student_fee_item id
  amount: number;
}

export interface RecordPaymentInput {
  student_fee_id: string;
  amount: number;
  method?: string;
  reference_number?: string;
  notes?: string;
  allocations?: PaymentAllocation[];
}
