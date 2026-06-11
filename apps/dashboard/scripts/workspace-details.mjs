import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';

dotenv.config();

const supabaseUrl = process.env.VITE_SUPABASE_URL || process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.VITE_SUPABASE_ANON_KEY;

const supabase = createClient(supabaseUrl, supabaseKey);

async function getWorkspaceDetails() {
  // Get all workspaces with owner info
  const { data: workspaces, error } = await supabase
    .from('workspaces')
    .select('*')
    .order('created_at', { ascending: true });

  if (error) {
    console.error('Error:', error.message);
    return;
  }

  console.log('\n📋 WORKSPACE DETAILS\n' + '='.repeat(70));

  for (const ws of workspaces) {
    // Get owner email from auth.users via profiles
    const { data: profile } = await supabase
      .from('profiles')
      .select('email, full_name, created_at')
      .eq('id', ws.owner_id)
      .single();

    // Get account count for this workspace owner
    const { count: accountCount } = await supabase
      .from('accounts')
      .select('*', { count: 'exact', head: true })
      .eq('user_id', ws.owner_id);

    // Get post count
    const { count: postCount } = await supabase
      .from('posts')
      .select('*', { count: 'exact', head: true })
      .eq('user_id', ws.owner_id);

    // Get last activity
    const { data: lastPost } = await supabase
      .from('posts')
      .select('created_at')
      .eq('user_id', ws.owner_id)
      .order('created_at', { ascending: false })
      .limit(1)
      .single();

    const createdDate = new Date(ws.created_at).toLocaleDateString();
    const lastActive = lastPost ? new Date(lastPost.created_at).toLocaleDateString() : 'Never';
    const tier = ws.subscription?.tier || 'free';
    const email = profile?.email || 'Unknown';
    const name = profile?.full_name || '-';

    console.log('\nWorkspace: ' + ws.name);
    console.log('  Owner:      ' + email);
    console.log('  Name:       ' + name);
    console.log('  Tier:       ' + tier.toUpperCase());
    console.log('  Created:    ' + createdDate);
    console.log('  Accounts:   ' + (accountCount || 0));
    console.log('  Posts:      ' + (postCount || 0));
    console.log('  Last Active:' + lastActive);
  }

  console.log('\n' + '='.repeat(70));
}

getWorkspaceDetails().catch(console.error);
