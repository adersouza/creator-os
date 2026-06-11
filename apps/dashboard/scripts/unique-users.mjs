import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.VITE_SUPABASE_ANON_KEY;

const supabase = createClient(supabaseUrl, supabaseKey);

async function getUniqueUsers() {
  console.log('\n👥 UNIQUE USERS ANALYSIS\n' + '='.repeat(70));

  // Get unique owner_ids from workspaces
  const { data: workspaces } = await supabase
    .from('workspaces')
    .select('owner_id, created_at, name');

  const uniqueOwners = [...new Set(workspaces?.map(w => w.owner_id))];
  console.log('\nTotal Workspaces: ' + workspaces?.length);
  console.log('Unique Owners: ' + uniqueOwners.length);

  // Show workspace distribution per owner
  const ownerCounts = {};
  workspaces?.forEach(w => {
    ownerCounts[w.owner_id] = (ownerCounts[w.owner_id] || 0) + 1;
  });

  console.log('\nWorkspaces per Owner:');
  for (const [ownerId, count] of Object.entries(ownerCounts)) {
    const shortId = ownerId.substring(0, 8) + '...';
    console.log('  ' + shortId + ': ' + count + ' workspace(s)');
  }

  // Get all accounts
  const { data: accounts } = await supabase
    .from('accounts')
    .select('id, user_id, username, followers, created_at, is_active');

  console.log('\n📱 CONNECTED ACCOUNTS:');
  accounts?.forEach(acc => {
    const shortUserId = acc.user_id.substring(0, 8) + '...';
    console.log('  @' + acc.username + ' (' + (acc.followers || 0) + ' followers)');
    console.log('    Owner: ' + shortUserId);
    console.log('    Active: ' + (acc.is_active ? 'Yes' : 'No'));
    console.log('    Connected: ' + new Date(acc.created_at).toLocaleDateString());
  });

  // Get profiles with auth info
  const { data: profiles } = await supabase
    .from('profiles')
    .select('*');

  console.log('\n👤 PROFILES TABLE:');
  console.log('  Count: ' + (profiles?.length || 0));
  if (profiles?.length > 0) {
    profiles.forEach(p => {
      console.log('  - ' + (p.email || p.full_name || p.id.substring(0, 8)));
    });
  }

  // Check auth.users if we have service role access
  const { data: authUsers, error: authError } = await supabase.auth.admin.listUsers();

  if (authError) {
    console.log('\n⚠️  Cannot access auth.users (need service role key)');
  } else {
    console.log('\n🔐 AUTH USERS:');
    authUsers?.users?.forEach(u => {
      console.log('  - ' + (u.email || 'No email'));
      console.log('    ID: ' + u.id.substring(0, 8) + '...');
      console.log('    Provider: ' + (u.app_metadata?.provider || 'unknown'));
      console.log('    Created: ' + new Date(u.created_at).toLocaleDateString());
      console.log('    Last Sign In: ' + (u.last_sign_in_at ? new Date(u.last_sign_in_at).toLocaleDateString() : 'Never'));
    });
  }

  console.log('\n' + '='.repeat(70));
}

getUniqueUsers().catch(console.error);
