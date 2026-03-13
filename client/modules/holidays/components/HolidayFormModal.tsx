import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, Modal, TextInput,
  TouchableOpacity, ScrollView, KeyboardAvoidingView,
  Platform, Switch,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from '@/common/constants/colors';
import { Spacing, Layout } from '@/common/constants/spacing';
import { Holiday, CreateHolidayDTO, HolidayType, HOLIDAY_TYPE_LABELS, DAY_NAMES } from '../types';
import { validateHolidayData } from '../validation/schemas';
import { DateField } from '@/common/components/DateField';
import { useAcademicYears } from '@/modules/academics/hooks/useAcademicYears';
import { useAcademicYearContext } from '@/modules/academics/context/AcademicYearContext';

interface HolidayFormModalProps {
  visible: boolean;
  onClose: () => void;
  onSubmit: (data: CreateHolidayDTO) => Promise<void>;
  initialData?: Holiday | null;
  mode?: 'create' | 'edit';
}

const HOLIDAY_TYPES: HolidayType[] = ['public', 'school', 'regional', 'optional', 'weekly_off'];
const TYPE_ICONS: Record<HolidayType, keyof typeof import('@expo/vector-icons').Ionicons['glyphMap']> = {
  public:    'flag-outline',
  school:    'school-outline',
  regional:  'map-outline',
  optional:  'star-outline',
  weekly_off: 'repeat-outline',
};

type HolidayMode = 'single' | 'range' | 'recurring';

function getDefaultForm(): {
  name: string; description: string; holiday_type: HolidayType;
  start_date: string; end_date: string; academic_year_id: string;
  is_recurring: boolean; recurring_day_of_week: number | null;
} {
  return {
    name: '', description: '', holiday_type: 'school',
    start_date: '', end_date: '', academic_year_id: '',
    is_recurring: false, recurring_day_of_week: null,
  };
}

export const HolidayFormModal: React.FC<HolidayFormModalProps> = ({
  visible, onClose, onSubmit, initialData = null, mode = 'create',
}) => {
  const [form, setForm] = useState(getDefaultForm());
  const [holidayMode, setHolidayMode] = useState<HolidayMode>('single');
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const { data: academicYears = [] } = useAcademicYears(false);
  const { selectedAcademicYearId } = useAcademicYearContext();

  // Populate form when editing
  useEffect(() => {
    if (!visible) return;
    if (mode === 'edit' && initialData) {
      setForm({
        name: initialData.name ?? '',
        description: initialData.description ?? '',
        holiday_type: initialData.holiday_type,
        start_date: initialData.start_date ?? '',
        end_date: initialData.end_date ?? '',
        academic_year_id: initialData.academic_year_id ?? '',
        is_recurring: initialData.is_recurring,
        recurring_day_of_week: initialData.recurring_day_of_week ?? null,
      });
      if (initialData.is_recurring) {
        setHolidayMode('recurring');
      } else if (initialData.start_date && initialData.end_date && initialData.start_date !== initialData.end_date) {
        setHolidayMode('range');
      } else {
        setHolidayMode('single');
      }
    } else {
      setForm({ ...getDefaultForm(), academic_year_id: selectedAcademicYearId ?? '' });
      setHolidayMode('single');
    }
    setFieldErrors({});
    setSubmitError(null);
  }, [visible, mode, initialData, selectedAcademicYearId]);

  const setField = <K extends keyof typeof form>(key: K, value: typeof form[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (fieldErrors[key]) {
      setFieldErrors((prev) => { const n = { ...prev }; delete n[key]; return n; });
    }
  };

  const handleModeChange = (m: HolidayMode) => {
    setHolidayMode(m);
    setFieldErrors({});
    setSubmitError(null);
    if (m === 'recurring') {
      setForm((prev) => ({ ...prev, is_recurring: true, start_date: '', end_date: '' }));
    } else {
      setForm((prev) => ({ ...prev, is_recurring: false, recurring_day_of_week: null }));
      if (m === 'single') {
        setForm((prev) => ({ ...prev, end_date: '' }));
      }
    }
  };

  const buildPayload = (): CreateHolidayDTO => {
    if (holidayMode === 'recurring') {
      return {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        holiday_type: form.holiday_type,
        is_recurring: true,
        recurring_day_of_week: form.recurring_day_of_week!,
        academic_year_id: form.academic_year_id || undefined,
      };
    }
    return {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      holiday_type: form.holiday_type,
      is_recurring: false,
      start_date: form.start_date.trim(),
      end_date: holidayMode === 'range' ? (form.end_date.trim() || undefined) : undefined,
      academic_year_id: form.academic_year_id || undefined,
    };
  };

  const handleSubmit = async () => {
    const payload = buildPayload();
    const validation = validateHolidayData(payload);
    if (!validation.valid) {
      setFieldErrors(validation.errors);
      setSubmitError('Please fix the errors below.');
      return;
    }

    setLoading(true);
    setSubmitError(null);
    setFieldErrors({});
    try {
      await onSubmit(payload);
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to save holiday');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.overlay}
      >
        <View style={styles.sheet}>
          {/* Header */}
          <View style={styles.header}>
            <Text style={styles.title}>
              {mode === 'edit' ? 'Edit Holiday' : 'Add Holiday'}
            </Text>
            <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
              <Ionicons name="close" size={24} color={Colors.text} />
            </TouchableOpacity>
          </View>

          {/* Error banner */}
          {submitError && (
            <View style={styles.errorBanner}>
              <Ionicons name="alert-circle-outline" size={16} color={Colors.error} />
              <Text style={styles.errorBannerText}>{submitError}</Text>
            </View>
          )}

          <ScrollView style={styles.form} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">

            {/* ─── Holiday Mode Tabs ─────────────────────────────── */}
            <Text style={styles.sectionLabel}>Holiday Type</Text>
            <View style={styles.modeTabs}>
              {(['single', 'range', 'recurring'] as HolidayMode[]).map((m) => (
                <TouchableOpacity
                  key={m}
                  style={[styles.modeTab, holidayMode === m && styles.modeTabActive]}
                  onPress={() => handleModeChange(m)}
                >
                  <Ionicons
                    name={m === 'single' ? 'today-outline' : m === 'range' ? 'calendar-outline' : 'repeat-outline'}
                    size={15}
                    color={holidayMode === m ? Colors.background : Colors.textSecondary}
                  />
                  <Text style={[styles.modeTabText, holidayMode === m && styles.modeTabTextActive]}>
                    {m === 'single' ? 'Single Day' : m === 'range' ? 'Date Range' : 'Recurring'}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* ─── Name ─────────────────────────────────────────── */}
            <Text style={styles.label}>Name *</Text>
            <TextInput
              style={[styles.input, fieldErrors.name && styles.inputError]}
              value={form.name}
              onChangeText={(v) => setField('name', v)}
              placeholder="e.g. Diwali, Summer Vacation, Sunday Off"
              placeholderTextColor={Colors.textSecondary}
            />
            {fieldErrors.name && <Text style={styles.fieldError}>{fieldErrors.name}</Text>}

            {/* ─── Date inputs ──────────────────────────────────── */}
            {holidayMode === 'single' && (
              <>
                <DateField
                  label="Date *"
                  value={form.start_date}
                  onChange={(v) => setField('start_date', v)}
                  placeholder="YYYY-MM-DD"
                  error={fieldErrors.start_date}
                  useOverlayInsideModal
                />
              </>
            )}

            {holidayMode === 'range' && (
              <View style={styles.row}>
                <View style={styles.col}>
                  <DateField
                    label="Start Date *"
                    value={form.start_date}
                    onChange={(v) => setField('start_date', v)}
                    placeholder="YYYY-MM-DD"
                    error={fieldErrors.start_date}
                    useOverlayInsideModal
                  />
                </View>
                <View style={[styles.col, { marginLeft: Spacing.md }]}>
                  <DateField
                    label="End Date *"
                    value={form.end_date}
                    onChange={(v) => setField('end_date', v)}
                    placeholder="YYYY-MM-DD"
                    error={fieldErrors.end_date}
                    useOverlayInsideModal
                  />
                </View>
              </View>
            )}

            {holidayMode === 'recurring' && (
              <>
                <Text style={styles.label}>Repeats Every *</Text>
                <View style={styles.dayGrid}>
                  {Object.entries(DAY_NAMES).map(([key, dayName]) => {
                    const dow = Number(key);
                    const active = form.recurring_day_of_week === dow;
                    return (
                      <TouchableOpacity
                        key={dow}
                        style={[styles.dayChip, active && styles.dayChipActive]}
                        onPress={() => {
                          setField('recurring_day_of_week', dow);
                          if (fieldErrors.recurring_day_of_week) {
                            setFieldErrors((p) => { const n = { ...p }; delete n.recurring_day_of_week; return n; });
                          }
                        }}
                      >
                        <Text style={[styles.dayChipText, active && styles.dayChipTextActive]}>
                          {dayName.slice(0, 3)}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
                {fieldErrors.recurring_day_of_week && (
                  <Text style={styles.fieldError}>{fieldErrors.recurring_day_of_week}</Text>
                )}
                <View style={styles.infoBox}>
                  <Ionicons name="information-circle-outline" size={14} color={Colors.textSecondary} />
                  <Text style={styles.infoText}>
                    Recurring holidays (e.g. every Sunday) apply across all weeks. They count
                    as weekly-off days — any public holiday that also falls on this day will show
                    a {'"' }Falls on Sunday{'"' } warning.
                  </Text>
                </View>
              </>
            )}

            {/* ─── Holiday Category ─────────────────────────────── */}
            <Text style={styles.label}>Category</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.typeRow}>
              {HOLIDAY_TYPES.map((t) => (
                <TouchableOpacity
                  key={t}
                  style={[styles.typeChip, form.holiday_type === t && styles.typeChipActive]}
                  onPress={() => setField('holiday_type', t)}
                >
                  <Ionicons
                    name={TYPE_ICONS[t]}
                    size={14}
                    color={form.holiday_type === t ? Colors.background : Colors.textSecondary}
                    style={{ marginRight: 4 }}
                  />
                  <Text style={[styles.typeChipText, form.holiday_type === t && styles.typeChipTextActive]}>
                    {HOLIDAY_TYPE_LABELS[t]}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            {fieldErrors.holiday_type && <Text style={styles.fieldError}>{fieldErrors.holiday_type}</Text>}

            {/* ─── Academic Year ────────────────────────────────── */}
            {academicYears.length > 0 && (
              <>
                <Text style={styles.label}>Academic Year</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.typeRow}>
                  <TouchableOpacity
                    style={[styles.typeChip, !form.academic_year_id && styles.typeChipActive]}
                    onPress={() => setField('academic_year_id', '')}
                  >
                    <Text style={[styles.typeChipText, !form.academic_year_id && styles.typeChipTextActive]}>
                      All Years
                    </Text>
                  </TouchableOpacity>
                  {academicYears.map((ay: any) => (
                    <TouchableOpacity
                      key={ay.id}
                      style={[styles.typeChip, form.academic_year_id === ay.id && styles.typeChipActive]}
                      onPress={() => setField('academic_year_id', ay.id)}
                    >
                      <Text style={[styles.typeChipText, form.academic_year_id === ay.id && styles.typeChipTextActive]}>
                        {ay.name}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              </>
            )}

            {/* ─── Description ─────────────────────────────────── */}
            <Text style={styles.label}>Description (optional)</Text>
            <TextInput
              style={[styles.input, styles.textArea, fieldErrors.description && styles.inputError]}
              value={form.description}
              onChangeText={(v) => setField('description', v)}
              placeholder="Additional details about this holiday…"
              placeholderTextColor={Colors.textSecondary}
              multiline
              numberOfLines={3}
              textAlignVertical="top"
            />
            {fieldErrors.description && <Text style={styles.fieldError}>{fieldErrors.description}</Text>}

            <View style={{ height: Spacing.xl }} />
          </ScrollView>

          {/* Footer */}
          <View style={styles.footer}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.submitBtn, loading && styles.disabledBtn]}
              onPress={handleSubmit}
              disabled={loading}
            >
              <Text style={styles.submitText}>
                {loading
                  ? (mode === 'edit' ? 'Saving…' : 'Adding…')
                  : (mode === 'edit' ? 'Save Changes' : 'Add Holiday')}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: Colors.background,
    borderTopLeftRadius: Layout.borderRadius.xl,
    borderTopRightRadius: Layout.borderRadius.xl,
    height: '90%',
    padding: Spacing.lg,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: Spacing.md,
  },
  title: { fontSize: 20, fontWeight: 'bold', color: Colors.text },
  closeBtn: { padding: Spacing.xs },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
    backgroundColor: '#FFF0F0',
    padding: Spacing.sm,
    borderRadius: Layout.borderRadius.sm,
    marginBottom: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.error + '30',
  },
  errorBannerText: { fontSize: 13, color: Colors.error, flex: 1 },
  form: { flex: 1 },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: Spacing.sm,
  },
  // Mode tabs
  modeTabs: {
    flexDirection: 'row',
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.md,
    padding: 3,
    marginBottom: Spacing.lg,
  },
  modeTab: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.sm,
    borderRadius: Layout.borderRadius.sm,
    gap: 4,
  },
  modeTabActive: { backgroundColor: Colors.primary },
  modeTabText: { fontSize: 13, fontWeight: '600', color: Colors.textSecondary },
  modeTabTextActive: { color: Colors.background },
  // Fields
  label: {
    fontSize: 14, fontWeight: '500', color: Colors.text,
    marginBottom: Spacing.xs, marginTop: Spacing.sm,
  },
  input: {
    backgroundColor: Colors.backgroundSecondary,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.md,
    color: Colors.text,
    fontSize: 16,
  },
  inputError: { borderColor: Colors.error, borderWidth: 2 },
  textArea: { minHeight: 80, paddingTop: Spacing.sm },
  fieldError: { color: Colors.error, fontSize: 12, marginTop: 3, marginBottom: 4 },
  row: { flexDirection: 'row' },
  col: { flex: 1 },
  // Day grid (recurring)
  dayGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.sm,
    marginBottom: Spacing.xs,
  },
  dayChip: {
    paddingVertical: Spacing.sm,
    paddingHorizontal: Spacing.md,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    backgroundColor: Colors.backgroundSecondary,
  },
  dayChipActive: { borderColor: Colors.primary, backgroundColor: Colors.primary },
  dayChipText: { fontSize: 13, fontWeight: '600', color: Colors.text },
  dayChipTextActive: { color: Colors.background },
  // Type chips
  typeRow: { marginBottom: Spacing.xs },
  typeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
    paddingHorizontal: Spacing.md,
    marginRight: Spacing.sm,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    backgroundColor: Colors.backgroundSecondary,
  },
  typeChipActive: { borderColor: Colors.primary, backgroundColor: Colors.primary },
  typeChipText: { fontSize: 13, fontWeight: '600', color: Colors.text },
  typeChipTextActive: { color: Colors.background },
  // Info box
  infoBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.xs,
    backgroundColor: Colors.backgroundSecondary,
    padding: Spacing.sm,
    borderRadius: Layout.borderRadius.sm,
    marginTop: Spacing.xs,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  infoText: { fontSize: 12, color: Colors.textSecondary, flex: 1, lineHeight: 18 },
  // Footer
  footer: {
    flexDirection: 'row',
    paddingTop: Spacing.md,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
  },
  cancelBtn: {
    flex: 1, padding: Spacing.md, alignItems: 'center', marginRight: Spacing.md,
  },
  cancelText: { fontSize: 16, color: Colors.textSecondary, fontWeight: '600' },
  submitBtn: {
    flex: 2, backgroundColor: Colors.primary, padding: Spacing.md,
    borderRadius: Layout.borderRadius.md, alignItems: 'center',
  },
  disabledBtn: { opacity: 0.65 },
  submitText: { fontSize: 16, color: '#FFFFFF', fontWeight: '600' },
});
