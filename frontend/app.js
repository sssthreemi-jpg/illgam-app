const $ = id => document.getElementById(id)
let token = null
let myCompany = null
const $select = id => document.getElementById(id)

function showError(msg){
  const el = $('result')
  el.innerHTML = `<div style="color:#b91c1c;font-weight:700">오류</div><div style="margin-top:6px">${msg}</div>`
  el.style.borderColor = '#f8d7da'
}

function showResult(obj){
  const el = $('result')
  el.innerHTML = `<pre style="white-space:pre-wrap;margin:0">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>`
  el.style.borderColor = '#dbefff'
}

async function post(path, body){
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', ...(token?{Authorization:'Bearer '+token}:{})}, body: JSON.stringify(body)})
  return res.json()
}

$('login').onclick = async ()=>{
  const username = $('username').value
  const password = $('password').value
  if(!username || !password){ showError('사용자명과 비밀번호를 입력하세요'); return }
  try{
    // try real API first
    const res = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password})})
    if(res.ok){
      const j = await res.json(); if(j && j.access_token){ token = j.access_token; document.getElementById('login-overlay').style.display='none'; document.getElementById('app').style.display='block'; await loadMyCompany(); return }
    }
  }catch(e){ /* ignore and fallback to mock */ }

  // fallback mock for development
  if(username === 'admin' && password === 'adminpass'){
    token = 'dev-token-admin'
    document.getElementById('login-overlay').style.display='none'
    document.getElementById('app').style.display='block'
    myCompany = {company:'admin'}
    $('mycompany').textContent = JSON.stringify(myCompany)
    $('company').value = myCompany.company
    $('company').removeAttribute('disabled')
    return
  }
  // other mock: accept any non-empty creds in dev
  if(window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost'){
    token = 'dev-token'
    document.getElementById('login-overlay').style.display='none'
    document.getElementById('app').style.display='block'
    myCompany = {company: username}
    $('mycompany').textContent = JSON.stringify(myCompany)
    $('company').value = myCompany.company
    if(myCompany.company !== 'admin') $('company').setAttribute('disabled','true')
    return
  }
  showError('로그인 실패')
}

// related_format picker: update textarea placeholder/sample
const relatedFormatEl = document.getElementById('related_format')
const relatedSalesEl = document.getElementById('related_sales')
if(relatedFormatEl && relatedSalesEl){
  relatedFormatEl.addEventListener('change', ()=>{
    const v = relatedFormatEl.value
    if(v === 'json'){
      relatedSalesEl.value = '{"대웅제약":900000}'
    } else {
      relatedSalesEl.value = '대웅제약,900000\n회사B,100000'
    }
  })
}

// Table helpers for related sales and tax adjustments
function getRelatedFromTable(){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return null
  const related = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const nameEl = tr.querySelector('.rname')
    const amtEl = tr.querySelector('.ramt')
    if(nameEl){
      const name = (nameEl.value||'').trim()
      const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
      if(name) related[name] = amt
    }
  })
  return related
}

function getTaxFromTable(){
  const tbody = document.querySelector('#tax_table tbody')
  if(!tbody) return null
  const obj = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const nameEl = tr.querySelector('.tname')
    const amtEl = tr.querySelector('.tamt')
    if(nameEl){
      const name = (nameEl.value||'').trim()
      const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
      if(name) obj[name] = amt
    }
  })
  return obj
}

// add/remove row handlers
document.addEventListener('click', (e)=>{
  if(e.target && e.target.id === 'add_related_row'){
    const tbody = document.querySelector('#related_table tbody')
    const tr = document.createElement('tr')
    tr.innerHTML = '<td style="padding:6px"><input class="rname"></td><td style="padding:6px"><input class="ramt"></td><td style="padding:6px"><button type="button" class="del_related">삭제</button></td>'
    tbody.appendChild(tr)
  }
  if(e.target && e.target.classList && e.target.classList.contains('del_related')){
    const tr = e.target.closest('tr'); if(tr) tr.remove()
  }
  if(e.target && e.target.id === 'add_tax_row'){
    const tbody = document.querySelector('#tax_table tbody')
    const tr = document.createElement('tr')
    tr.innerHTML = '<td style="padding:6px"><input class="tname"></td><td style="padding:6px"><input class="tamt"></td><td style="padding:6px"><button type="button" class="del_tax">삭제</button></td>'
    tbody.appendChild(tr)
  }
  if(e.target && e.target.classList && e.target.classList.contains('del_tax')){
    const tr = e.target.closest('tr'); if(tr) tr.remove()
  }
})

// Download handlers: simple CSV export and print
document.getElementById('excel-download')?.addEventListener('click', ()=>{
  // build CSV from related and tax tables
  const related = getRelatedFromTable() || {}
  const tax = getTaxFromTable() || {}
  let csv = 'Section,Name,Amount\n'
  Object.entries(related).forEach(([k,v])=> csv += `Related,${k},${v}\n`)
  Object.entries(tax).forEach(([k,v])=> csv += `TaxAdjust,${k},${v}\n`)
  const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'report_export.csv'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
})

document.getElementById('pdf-download')?.addEventListener('click', ()=>{
  window.print()
})

async function loadMyCompany(){
  const res = await fetch('/api/my-company',{headers: token?{Authorization:'Bearer '+token}:{}})
  if(!res.ok){ showError('내 법인 정보를 불러오지 못했습니다'); return }
  const j = await res.json()
  myCompany = j
  $('mycompany').textContent = JSON.stringify(j)
  $('hint').textContent = ''
  // set company field to user's company and lock unless admin
  $('company').value = j.company || ''
  if(j.company !== 'admin'){
    $('company').setAttribute('disabled','true')
    $('hint').textContent = '(관리자 아님 — 법인 필드 잠김)'
  } else {
    $('company').removeAttribute('disabled')
  }
  // fetch companies list for optional UI later
  try{
    const c = await fetch('/api/companies',{headers: token?{Authorization:'Bearer '+token}:{}})
    if(c.ok){ const cl = await c.json(); console.log('companies', cl) }
  }catch(e){ /* ignore */ }
}

$('evaluate').onclick = async ()=>{
  // validation
  try{
    // read related sales from table if present, otherwise fallback to textarea/csv/json
    let related = {}
    const tableRelated = getRelatedFromTable()
    if(tableRelated && Object.keys(tableRelated).length>0){
      related = tableRelated
    } else {
      const rawRelated = (document.getElementById('related_sales') && document.getElementById('related_sales').value) || ''
      if(($select('related_format') && $select('related_format').value === 'csv') || (rawRelated.indexOf('\n') !== -1 && rawRelated.indexOf('{') === -1)){
        rawRelated.split(/\r?\n/).forEach(line=>{
          const [name,amt] = line.split(',').map(s=>s && s.trim())
          if(name){ related[name] = Number(amt || 0) }
        })
      } else {
        try{ related = JSON.parse(rawRelated || '{}') }catch(e){ related = {} }
      }
    }
    const company = $('company').value
    if(!company){ showError('법인을 선택하세요'); return }
    // ensure company matches logged-in user's company unless admin
    if(myCompany && myCompany.company !== 'admin' && company !== myCompany.company){ showError('자기 법인만 판정할 수 있습니다'); return }
    const operating_income = Number($('operating_income').value)
    const corporate_tax = Number($('corporate_tax').value)
    const corporate_tax_expense = Number($('corporate_tax_expense') ? $('corporate_tax_expense').value : 0)
    const total_sales = Number($('total_sales').value)
    if(Number.isNaN(operating_income) || Number.isNaN(corporate_tax) || Number.isNaN(total_sales)){
      showError('숫자 필드에 유효한 값을 입력하세요'); return
    }
    if(total_sales < 0 || operating_income < 0 || corporate_tax < 0){ showError('음수 값은 허용되지 않습니다'); return }

    // read tax adjustments from table if present, otherwise fallback to textarea
    let tax_adjustments = {}
    const tableTax = getTaxFromTable()
    if(tableTax && Object.keys(tableTax).length>0){ tax_adjustments = tableTax }
    else {
      try{ tax_adjustments = JSON.parse(($('tax_adjustments') && $('tax_adjustments').value) || '{}') }catch(e){ tax_adjustments = {} }
    }

    const body = {
      company, operating_income, corporate_tax, total_sales, related_sales: related, tax_adjustments, corporate_tax_expense
    }
    const r = await post('/api/evaluate', body)
    if(r && (r.reason || r.summary || r.gift_tax_total)) {
      renderReport(r)
    } else {
      showError('서버 응답을 확인하세요')
    }
  } catch(e){ showError('거래처 매출 JSON 형식이 올바르지 않습니다'); }
}

function formatNum(n){ if(n===undefined || n===null) return '—'; if(typeof n==='number') return n.toLocaleString(); try{ return Number(n).toLocaleString() }catch(e){ return String(n) }}

function renderReport(r){
  const el = $('result')
  // basic judgement
  const judgment = r.reason || r.judgement || r.summary || '판정 결과 없음'
  // breakdown fields (best-effort)
  const se = formatNum(r.se_taxable_income || r.se_taxable || r.taxable_income || r.se_earnings)
  const gift = formatNum(r.gift_tax_total || r.gift_tax || r.gift_total)
  const deemed = formatNum(r.deemed_total || r.deemed)
  const details = r.details || r

  el.innerHTML = `
    <div style="border-bottom:1px solid #eef6ff;padding-bottom:8px;margin-bottom:8px"><strong style="color:var(--brand, #0b5ed7)">판정 요약</strong><div style="margin-top:6px;color:#374151">${judgment}</div></div>

    <div style="margin-bottom:10px">
      <table style="width:100%;border-collapse:collapse">
        <tr><td style="padding:8px;border:1px solid #eef6ff;width:60%"><strong>세무조정후 영업이익</strong></td><td style="padding:8px;border:1px solid #eef6ff">${formatNum(r.operating_income || r.se_ebit)}</td></tr>
        <tr><td style="padding:8px;border:1px solid #eef6ff"><strong>특수관계 매출비율</strong></td><td style="padding:8px;border:1px solid #eef6ff">${formatNum(r.related_ratio)}</td></tr>
        <tr><td style="padding:8px;border:1px solid #eef6ff"><strong>주식보유비율(합계)</strong></td><td style="padding:8px;border:1px solid #eef6ff">${formatNum(r.share_ratio)}</td></tr>
      </table>
    </div>

    <div style="margin-bottom:10px">
      <table style="width:100%;border-collapse:collapse">
        <tr><td style="padding:8px;border:1px solid #eef6ff"><strong>세무조정영업이익</strong></td><td style="padding:8px;border:1px solid #eef6ff">${se}</td></tr>
        <tr><td style="padding:8px;border:1px solid #eef6ff"><strong>의제총액(증여의제)</strong></td><td style="padding:8px;border:1px solid #eef6ff">${deemed}</td></tr>
        <tr><td style="padding:8px;border:1px solid #eef6ff"><strong>증여세 산출세액</strong></td><td style="padding:8px;border:1px solid #eef6ff">${gift}</td></tr>
      </table>
    </div>

    <div>
      <strong style="color:#334155">세부 항목</strong>
      <pre style="white-space:pre-wrap;margin-top:8px">${escapeHtml(JSON.stringify(details, null, 2))}</pre>
    </div>
  `
}

function escapeHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') }
