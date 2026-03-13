import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '@/modules/auth/hooks/useAuth';
import { usePermissions } from '@/modules/permissions/hooks/usePermissions';
import { Protected } from '@/modules/permissions/components/Protected';
import * as PERMS from '@/modules/permissions/constants/permissions';
import { isAdmin, isTeacher, getUserRole } from '@/common/constants/navigation';
import { ScreenContainer } from '@/src/components/ui/ScreenContainer';
import { theme } from '@/src/design-system/theme';
import { Icons } from '@/src/design-system/icons';

const ROLE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  Admin:   { bg: theme.colors.primary[50],  text: theme.colors.primary[600],  border: theme.colors.primary[200] },
  Teacher: { bg: '#e0f2fe',                 text: '#0369a1',                   border: '#bae6fd' },
  Student: { bg: '#dcfce7',                 text: '#15803d',                   border: '#bbf7d0' },
  Parent:  { bg: theme.colors.warningLight, text: '#92400e',                   border: '#fde68a' },
};

interface QuickAction {
  icon: React.ReactNode;
  label: string;
  onPress: () => void;
  color: string;
}

function ActionGrid({ actions }: { actions: QuickAction[] }) {
  return (
    <View style={styles.actionsGrid}>
      {actions.map((a, i) => (
        <TouchableOpacity key={i} style={styles.actionCard} onPress={a.onPress} activeOpacity={0.75}>
          <View style={[styles.actionIcon, { backgroundColor: a.color + '1a' }]}>
            {a.icon}
          </View>
          <Text style={styles.actionLabel} numberOfLines={2}>{a.label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

function SectionTitle({ children }: { children: string }) {
  return <Text style={styles.sectionTitle}>{children}</Text>;
}

export const DashboardScreen = () => {
  const { user, isFeatureEnabled } = useAuth();
  const { permissions } = usePermissions();
  const router = useRouter();

  const role = getUserRole(permissions);
  const roleStyle = ROLE_COLORS[role] ?? ROLE_COLORS.Admin;
  const adminUser = isAdmin(permissions);
  const teacherUser = isTeacher(permissions);

  const push = (path: string) => router.push(path as any);

  // ── ADMIN ACTIONS ──────────────────────────────────────────────────────────
  const adminActions: QuickAction[] = [
    isFeatureEnabled('student_management') && {
      icon: <Icons.Student size={22} color={theme.colors.primary[500]} />,
      label: 'Students',
      onPress: () => push('/(protected)/students'),
      color: theme.colors.primary[500],
    },
    isFeatureEnabled('teacher_management') && {
      icon: <Icons.Users size={22} color='#0ea5e9' />,
      label: 'Teachers',
      onPress: () => push('/(protected)/teachers'),
      color: '#0ea5e9',
    },
    isFeatureEnabled('class_management') && {
      icon: <Icons.Class size={22} color='#8b5cf6' />,
      label: 'Classes',
      onPress: () => push('/(protected)/classes'),
      color: '#8b5cf6',
    },
    isFeatureEnabled('attendance') && {
      icon: <Icons.Calendar size={22} color={theme.colors.warning} />,
      label: 'Attendance',
      onPress: () => push('/(protected)/attendance/overview'),
      color: theme.colors.warning,
    },
    isFeatureEnabled('fees_management') && {
      icon: <Icons.Finance size={22} color={theme.colors.success} />,
      label: 'Finance',
      onPress: () => push('/(protected)/finance'),
      color: theme.colors.success,
    },
    isFeatureEnabled('teacher_management') && {
      icon: <Icons.FileText size={22} color={theme.colors.danger} />,
      label: 'Leave Requests',
      onPress: () => push('/(protected)/teacher-leaves'),
      color: theme.colors.danger,
    },
  ].filter(Boolean) as QuickAction[];

  // ── TEACHER ACTIONS ────────────────────────────────────────────────────────
  const teacherActions: QuickAction[] = [
    isFeatureEnabled('attendance') && {
      icon: <Icons.CheckMark size={22} color='#0ea5e9' />,
      label: 'Mark Attendance',
      onPress: () => push('/(protected)/attendance/my-classes'),
      color: '#0ea5e9',
    },
    {
      icon: <Icons.Calendar size={22} color='#8b5cf6' />,
      label: 'My Schedule',
      onPress: () => push('/(protected)/schedule/today'),
      color: '#8b5cf6',
    },
    isFeatureEnabled('teacher_management') && {
      icon: <Icons.FileText size={22} color={theme.colors.warning} />,
      label: 'My Leaves',
      onPress: () => push('/(protected)/my-leaves'),
      color: theme.colors.warning,
    },
    {
      icon: <Icons.Class size={22} color={theme.colors.success} />,
      label: 'Academics',
      onPress: () => push('/(protected)/academics'),
      color: theme.colors.success,
    },
  ].filter(Boolean) as QuickAction[];

  // ── STUDENT ACTIONS ────────────────────────────────────────────────────────
  const studentActions: QuickAction[] = [
    isFeatureEnabled('attendance') && {
      icon: <Icons.Calendar size={22} color='#0ea5e9' />,
      label: 'My Attendance',
      onPress: () => push('/(protected)/attendance/my-attendance'),
      color: '#0ea5e9',
    },
    {
      icon: <Icons.Class size={22} color={theme.colors.success} />,
      label: 'Academics',
      onPress: () => push('/(protected)/academics'),
      color: theme.colors.success,
    },
    isFeatureEnabled('fees_management') && {
      icon: <Icons.Finance size={22} color={theme.colors.warning} />,
      label: 'My Fees',
      onPress: () => push('/(protected)/finance'),
      color: theme.colors.warning,
    },
    {
      icon: <Icons.Profile size={22} color={theme.colors.primary[500]} />,
      label: 'Profile',
      onPress: () => push('/(protected)/profile'),
      color: theme.colors.primary[500],
    },
  ].filter(Boolean) as QuickAction[];

  const displayName = user?.name?.split(' ')[0] || user?.email?.split('@')[0] || 'there';

  return (
    <ScreenContainer>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={styles.contentContainer}
      >
        {/* Greeting */}
        <View style={styles.greeting}>
          <Text style={styles.greetSubtitle}>Welcome back,</Text>
          <Text style={styles.greetName}>{displayName}</Text>
          <View style={[styles.roleBadge, { backgroundColor: roleStyle.bg, borderColor: roleStyle.border }]}>
            <Text style={[styles.roleText, { color: roleStyle.text }]}>{role}</Text>
          </View>
        </View>

        {/* Admin quick actions */}
        {adminUser && adminActions.length > 0 && (
          <View style={styles.section}>
            <SectionTitle>Management</SectionTitle>
            <Protected anyPermissions={[PERMS.STUDENT_READ_ALL, PERMS.TEACHER_READ, PERMS.CLASS_READ]}>
              <ActionGrid actions={adminActions} />
            </Protected>
          </View>
        )}

        {/* Teacher quick actions */}
        {teacherUser && !adminUser && teacherActions.length > 0 && (
          <View style={styles.section}>
            <SectionTitle>Quick Actions</SectionTitle>
            <ActionGrid actions={teacherActions} />
          </View>
        )}

        {/* Student/Parent quick actions */}
        {!adminUser && !teacherUser && studentActions.length > 0 && (
          <View style={styles.section}>
            <SectionTitle>Quick Actions</SectionTitle>
            <ActionGrid actions={studentActions} />
          </View>
        )}
      </ScrollView>
    </ScreenContainer>
  );
};

const styles = StyleSheet.create({
  contentContainer: {
    paddingBottom: theme.spacing.xxl,
  },
  greeting: {
    paddingHorizontal: theme.spacing.m,
    paddingTop: theme.spacing.xl,
    paddingBottom: theme.spacing.l,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
    marginBottom: theme.spacing.l,
  },
  greetSubtitle: {
    ...theme.typography.body,
    color: theme.colors.text[500],
  },
  greetName: {
    ...theme.typography.h1,
    color: theme.colors.text[900],
    marginTop: theme.spacing.xs,
    marginBottom: theme.spacing.s,
  },
  roleBadge: {
    paddingHorizontal: theme.spacing.m,
    paddingVertical: theme.spacing.xs,
    borderRadius: theme.radius.full,
    borderWidth: 1,
    alignSelf: 'flex-start',
  },
  roleText: {
    ...theme.typography.caption,
    fontWeight: '600',
  },
  section: {
    paddingHorizontal: theme.spacing.m,
    marginBottom: theme.spacing.xl,
  },
  sectionTitle: {
    ...theme.typography.overline,
    color: theme.colors.text[500],
    marginBottom: theme.spacing.m,
  },
  actionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: theme.spacing.s,
  },
  actionCard: {
    width: '47%',
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.xl,
    padding: theme.spacing.m,
    alignItems: 'center',
    gap: theme.spacing.s,
    borderWidth: 1,
    borderColor: theme.colors.border,
    ...theme.shadows.sm,
  },
  actionIcon: {
    width: 50,
    height: 50,
    borderRadius: theme.radius.l,
    justifyContent: 'center',
    alignItems: 'center',
  },
  actionLabel: {
    ...theme.typography.caption,
    fontWeight: '500',
    color: theme.colors.text[900],
    textAlign: 'center',
  },
});
