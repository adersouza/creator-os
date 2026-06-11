import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.VITE_SUPABASE_ANON_KEY;

const supabase = createClient(supabaseUrl, supabaseKey);

async function cleanup() {
  console.log('\n🧹 CLEANUP TEST DATA\n' + '='.repeat(50));

  // Find the test account owner (D2BgURjS...)
  const { data: workspaces } = await supabase
    .from('workspaces')
    .select('owner_id')
    .order('created_at', { ascending: true });

  // Get unique owners
  const ownerCounts = {};
  workspaces?.forEach(w => {
    ownerCounts[w.owner_id] = (ownerCounts[w.owner_id] || 0) + 1;
  });

  // Find the one with only 1 workspace (test account)
  const testOwnerId = Object.entries(ownerCounts).find(([id, count]) => count === 1)?.[0];

  if (!testOwnerId) {
    console.log('No test account found to delete');
    return;
  }

  console.log('Test account owner ID: ' + testOwnerId.substring(0, 8) + '...');

  // Delete workspace for test account
  const { error: wsError, count: wsCount } = await supabase
    .from('workspaces')
    .delete()
    .eq('owner_id', testOwnerId);

  if (wsError) {
    console.log('Error deleting workspace: ' + wsError.message);
  } else {
    console.log('✓ Deleted workspace(s)');
  }

  // Delete profile for test account
  const { error: profileError } = await supabase
    .from('profiles')
    .delete()
    .eq('id', testOwnerId);

  if (profileError) {
    console.log('Error deleting profile: ' + profileError.message);
  } else {
    console.log('✓ Deleted profile');
  }

  // Delete any accounts owned by test user
  const { error: accError } = await supabase
    .from('accounts')
    .delete()
    .eq('user_id', testOwnerId);

  if (!accError) {
    console.log('✓ Deleted any connected accounts');
  }

  // Delete any posts by test user
  const { error: postError } = await supabase
    .from('posts')
    .delete()
    .eq('user_id', testOwnerId);

  if (!postError) {
    console.log('✓ Deleted any posts');
  }

  // Also clean up duplicate workspaces for the main user (keep only the oldest one)
  const mainOwnerId = Object.entries(ownerCounts).find(([id, count]) => count > 1)?.[0];

  if (mainOwnerId) {
    const { data: mainWorkspaces } = await supabase
      .from('workspaces')
      .select('id, created_at')
      .eq('owner_id', mainOwnerId)
      .order('created_at', { ascending: true });

    if (mainWorkspaces && mainWorkspaces.length > 1) {
      // Keep the first one, delete the rest
      const keepId = mainWorkspaces[0].id;
      const deleteIds = mainWorkspaces.slice(1).map(w => w.id);

      console.log('\nCleaning up ' + deleteIds.length + ' duplicate workspaces for main user...');

      const { error: dupError } = await supabase
        .from('workspaces')
        .delete()
        .in('id', deleteIds);

      if (dupError) {
        console.log('Error deleting duplicates: ' + dupError.message);
      } else {
        console.log('✓ Deleted ' + deleteIds.length + ' duplicate workspaces');
      }
    }
  }

  // Final count
  const { count: finalCount } = await supabase
    .from('workspaces')
    .select('*', { count: 'exact', head: true });

  console.log('\n📊 FINAL STATE:');
  console.log('Workspaces remaining: ' + finalCount);

  console.log('\n' + '='.repeat(50));
}

cleanup().catch(console.error);
