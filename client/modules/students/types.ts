
export interface Student {
  id: string;
  user_id: string;
  name: string;
  email: string;
  profile_picture?: string;
  admission_number: string;
  academic_year?: string;
  academic_year_id?: string;
  roll_number?: number;
  class_id?: string;
  class_name?: string;
  date_of_birth?: string;
  gender?: string;
  phone?: string;
  address?: string;
  guardian_name?: string;
  guardian_relationship?: string;
  guardian_phone?: string;
  guardian_email?: string;
  created_at: string;
}

export interface Class {
  id: string;
  name: string;
  section: string;
  academic_year: string;
  teacher_id?: string;
  teacher_name?: string;
  created_at: string;
}

export interface CreateStudentDTO {
  // Required fields
  name: string;
  guardian_name: string;
  guardian_relationship: string;
  guardian_phone: string;
  
  // Academic: either class_id (derives academic year) or academic_year_id
  class_id?: string;
  academic_year_id?: string;
  
  // Optional fields
  admission_number?: string; // Auto-generated if not provided
  email?: string;
  phone?: string;
  date_of_birth?: string;
  gender?: string;
  roll_number?: number;
  address?: string;
  guardian_email?: string;
}

export interface StudentCredentials {
  username: string; // Admission number
  email: string; // Student email
  password: string; // First 3 letters + birth year
  must_reset: boolean;
}

export interface CreateStudentResponse {
  student: Student;
  credentials?: StudentCredentials;
}

export interface UpdateStudentDTO extends Partial<CreateStudentDTO> {}

// Document types for student documents (must match backend DocumentType enum)
export type DocumentType =
  | 'aadhar_card'
  | 'birth_certificate'
  | 'leaving_certificate'
  | 'transfer_certificate'
  | 'passport'
  | 'other';

/** Alias for DocumentType (used in upload modal) */
export type DocumentTypeValue = DocumentType;

/** All document type values for the type picker */
export const DOCUMENT_TYPES: DocumentType[] = [
  'aadhar_card',
  'birth_certificate',
  'leaving_certificate',
  'transfer_certificate',
  'passport',
  'other',
];

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  aadhar_card: 'Aadhar Card',
  birth_certificate: 'Birth Certificate',
  leaving_certificate: 'Leaving Certificate',
  transfer_certificate: 'Transfer Certificate',
  passport: 'Passport',
  other: 'Other',
};

export interface StudentDocument {
  id: string;
  student_id: string;
  document_type: string;
  document_type_label: string;
  original_filename: string;
  cloudinary_url: string;
  mime_type: string;
  file_size_bytes: number;
  uploaded_by?: { id: string; name: string } | null;
  created_at: string;
}

export interface UploadDocumentInput {
  documentType: string;
  file: { uri: string; name: string; mimeType?: string };
}
