const $ = id => document.getElementById(id)
let token = null
let myCompany = null
let lastReviewInput = null
// 거래처 표와 엑셀 업로드 결과가 같은 목록을 써야 한다. /api/companies 응답을 그대로 담는다.
let allCompanies = []
// 서버 calc.OTHER_COMPANY 와 같은 문자열이어야 한다. /api/companies 목록에 포함돼 내려온다.
const OTHER_COMPANY = '기타법인'

function showError(msg){
  const formError = $('form-error')
  if(formError && $('result-page').hidden){
    formError.textContent = msg
    return
  }
  const el = $('result')
  el.innerHTML = `<div style="color:#b91c1c;font-weight:700">오류</div><div style="margin-top:6px">${escapeHtml(msg)}</div>`
  el.style.borderColor = '#f8d7da'
}

async function post(path, body){
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json', ...(token?{Authorization:'Bearer '+token}:{})}, body: JSON.stringify(body)})
  const data = await res.json().catch(()=>null)
  if(!res.ok){
    const detail = data && (data.detail || data.message)
    throw new Error(detail || `서버 오류 (${res.status})`)
  }
  return data
}

function showLoginError(msg){
  const el = $('login-error')
  if(el) el.textContent = msg
}

// 로그인은 서버 인증만 사용한다. 이 화면 자체를 백엔드가 서빙하므로(StaticFiles 마운트)
// 페이지가 열렸다면 API 는 이미 떠 있다 — 개발용 mock 로그인은 반쪽짜리 세션만 만들어 제거했다.
$('login').onclick = async ()=>{
  const username = $('username').value
  const password = $('password').value
  showLoginError('')
  if(!username || !password){ showLoginError('사용자명과 비밀번호를 입력하세요'); return }
  try{
    const j = await post('/api/auth/login', {username, password})
    if(!j || !j.access_token) throw new Error('서버 응답에 토큰이 없습니다')
    token = j.access_token
    $('login-overlay').style.display = 'none'
    $('app').style.display = 'block'
    await loadMyCompany()
    // 마크업이 낡은 브라우저 캐시로 들어오면 #nav 가 없다. 그때 여기서 터지면
    // catch 가 token 을 지워버려, 화면은 로그인된 채로 인증만 풀린 상태가 된다.
    const nav = $('nav')
    if(nav){ nav.hidden = false; syncNav() }
    showPage('input-page')
  }catch(e){
    token = null
    showLoginError(e.message || '로그인에 실패했습니다')
  }
}

// 로그인 카드는 <form> 이 아니라 Enter 가 먹지 않는다. 두 입력란 모두에서 Enter 로 제출되게 한다.
;['username','password'].forEach(id=>{
  $(id)?.addEventListener('keydown', e=>{ if(e.key === 'Enter'){ e.preventDefault(); $('login').click() } })
})

// Table helpers for related sales and tax adjustments
// 0 인 행은 계산에 영향이 없고(서버가 0 매출을 건너뛴다) 결과 리포트만 지저분하게 만들어 제외한다.
function getRelatedFromTable(){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return {}
  const related = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.company || ''
    const amtEl = tr.querySelector('.ramt')
    const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
    if(name && amt) related[name] = amt
  })
  return related
}

// 지배주주별 배당소득. 관리자에게만 표가 그려지므로 그 외에는 빈 객체가 된다.
function getDividendFromTable(){
  const tbody = document.querySelector('#dividend_table tbody')
  if(!tbody) return {}
  const out = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const code = tr.dataset.code || ''
    const v = Number(tr.querySelector('.dvd')?.value || 0)
    if(code && v) out[code] = v
  })
  return out
}

// 관리자에게만 배당소득 공제 입력란을 그린다.
function renderDividendSection(codes){
  const section = document.getElementById('dividend-section')
  const tbody = document.querySelector('#dividend_table tbody')
  if(!section || !tbody) return
  if(!codes || !codes.length){ section.style.display = 'none'; return }
  section.style.display = ''
  tbody.innerHTML = codes.map(code => `
    <tr data-code="${escapeHtml(code)}"><td>${escapeHtml(code)}</td><td><input class="dvd" type="number" min="0" value="0" placeholder="0"></td></tr>
  `).join('')
}

// 제10항 과세제외액. 매출이 0 인 행은 서버가 건너뛰므로 함께 뺀다.
function getArticle10FromTable(){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return {}
  const out = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.company || ''
    const amt = Number(tr.querySelector('.ramt')?.value || 0)
    const ex = Number(tr.querySelector('.rex')?.value || 0)
    if(name && amt && ex) out[name] = ex
  })
  return out
}

function getTaxFromTable(){
  const tbody = document.querySelector('#tax_table tbody')
  if(!tbody) return {}
  const obj = {}
  Array.from(tbody.querySelectorAll('tr')).forEach(tr=>{
    const name = tr.dataset.taxItem || ''
    const amtEl = tr.querySelector('.tamt')
    const amt = Number(amtEl && amtEl.value ? amtEl.value : 0)
    if(name && amt) obj[name] = amt
  })
  return obj
}

document.addEventListener('input', (e)=>{
  if(e.target && e.target.classList.contains('tamt')) updateTaxTotal()
})

function updateTaxTotal(){
  const total = Array.from(document.querySelectorAll('#tax_table .tamt'))
    .reduce((sum, input) => sum + (Number(input.value) || 0), 0)
  if($('tax-total')) $('tax-total').value = `${formatNum(total)}원`
}

// Download handlers: simple CSV export and print
document.getElementById('excel-download')?.addEventListener('click', ()=>{
  // build CSV from related and tax tables
  const related = getRelatedFromTable()
  const tax = getTaxFromTable()
  const cell = s => `"${String(s).replace(/"/g,'""')}"`
  let csv = '구분,항목,금액\n'
  Object.entries(related).forEach(([k,v])=> csv += `특수관계자매출,${cell(k)},${v}\n`)
  Object.entries(tax).forEach(([k,v])=> csv += `세무조정,${cell(k)},${v}\n`)
  // Excel 은 BOM 이 없는 UTF-8 CSV 를 ANSI 로 열어 한글이 깨진다.
  const BOM = String.fromCharCode(0xFEFF)
  const blob = new Blob([BOM + csv], {type:'text/csv;charset=utf-8;'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'report_export.csv'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
})

document.getElementById('pdf-download')?.addEventListener('click', ()=>{
  window.print()
})

// --- 검토 연도 ---------------------------------------------------------------
// 지분·기업규모·세율은 해마다 바뀌므로 서버가 연도별 데이터를 들고 있다.
// 화면은 연도를 골라 보내기만 하고, 어떤 데이터가 쓰였는지는 응답의 year 로 확인한다.

let currentYear = null
let yearAsOf = {}    // {연도: 기준시점 문구}

function yearQuery(prefix = '?'){
  return currentYear ? `${prefix}year=${encodeURIComponent(currentYear)}` : ''
}

function updateYearHint(){
  const el = $('year-as-of')
  if(!el) return
  const asOf = yearAsOf[currentYear]
  el.textContent = asOf
    ? `기준시점: ${asOf}`
    : '서버에 저장된 연도별 지분·규모 데이터로 계산합니다.'
}

async function apiGet(path){
  const res = await fetch(path, {headers: token ? {Authorization:'Bearer '+token} : {}})
  const data = await res.json().catch(()=>null)
  if(!res.ok) throw new Error((data && data.detail) || `서버 오류 (${res.status})`)
  return data
}

async function loadYears(){
  const select = $('data_year')
  if(!select) return
  try{
    const j = await apiGet('/api/years')
    const years = j.years || []
    yearAsOf = {}
    years.forEach(o => { yearAsOf[o.year] = o.as_of || '' })
    select.innerHTML = years
      .map(o => `<option value="${escapeHtml(o.year)}">${escapeHtml(o.year)}년</option>`).join('')
    currentYear = j.default || (years[0] && years[0].year) || null
    if(currentYear) select.value = currentYear
    // 연도가 하나뿐이면 고를 것이 없다.
    select.disabled = years.length <= 1
  }catch(e){
    select.innerHTML = '<option value="">(연도를 불러오지 못했습니다)</option>'
    select.disabled = true
  }
  updateYearHint()
}

async function loadMyCompany(){
  await loadYears()
  await refreshForYear({preserveAmounts: false})
}

async function refreshForYear({preserveAmounts = true} = {}){
  // 연도를 바꿔도 이미 입력한 금액을 날리지 않는다. 그 연도에 없는 거래처만 빠진다.
  const previous = preserveAmounts ? getRelatedFromTable() : null

  let j
  try{
    j = await apiGet(`/api/my-company${yearQuery()}`)
  }catch(e){
    showError(e.message || '내 법인 정보를 불러오지 못했습니다')
    return
  }
  myCompany = j
  renderDividendSection(j && j.shareholder_codes)
  $('mycompany').textContent = j.size ? `${j.company} · ${j.size}` : (j.company || '')
  $('hint').textContent = ''

  const companySelect = $('company')
  const keepCompany = companySelect.value
  // Populate only the public company-name list. Sensitive ownership data stays server-side.
  try{
    const cl = await apiGet(`/api/companies${yearQuery()}`)
    const all = cl.companies || []
    allCompanies = all
    companySelect.innerHTML = '<option value="">법인을 선택하세요</option>'
    // 판정 대상은 실제 법인만 — 기타법인은 거래처(매출 입력)로만 쓰인다.
    all.filter(name => name !== OTHER_COMPANY).forEach(name=>{
      const option = document.createElement('option')
      option.value = name
      option.textContent = name
      companySelect.appendChild(option)
    })
    // 거래처 표는 서버 목록을 그대로 쓴다. 프론트에서 이름을 만들지 않는다.
    renderRelatedCompanies(all)
    if(keepCompany && all.includes(keepCompany)) companySelect.value = keepCompany
  }catch(e){
    showError(e.message || '법인 목록을 불러오지 못했습니다')
    return
  }

  if(previous){
    applyRelatedAmounts(previous)
    // 사라진 거래처에 금액이 있었다면 조용히 넘어가지 않고 알린다.
    const dropped = Object.keys(previous)
      .filter(name => Number(previous[name]) > 0 && !allCompanies.includes(name))
    setImportStatus(dropped.length
      ? `${currentYear}년 데이터에 없는 거래처 ${dropped.length}건의 입력값이 빠졌습니다: ${dropped.join(', ')}`
      : '')
  }

  if(j.company !== 'admin'){
    companySelect.value = j.company || ''
    companySelect.setAttribute('disabled','true')
    $('hint').textContent = '(관리자 아님 — 법인 필드 잠김)'
    // 기업 구분은 서버가 보유한 값이 유일한 근거다. 관리자는 법인을 바꿀 수 있어
    // 판정 전까지 알 수 없으므로, 최종 표시는 응답의 size(renderReport)를 따른다.
    if(j.size && ['일반','중견','중소'].includes(j.size)) $('company_size').value = j.size
  } else {
    $('rawdata-button').style.display = 'inline-block'
    companySelect.removeAttribute('disabled')
    if(companySelect.options.length > 1 && !companySelect.value) companySelect.value = companySelect.options[1].value
    // 관리자는 법인을 바꿀 수 있어 판정 전에는 기업 구분을 알 수 없다.
    $('company_size').value = ''
  }
}

document.getElementById('data_year')?.addEventListener('change', async (e)=>{
  currentYear = e.target.value || null
  updateYearHint()
  // 연도가 바뀌면 지분·규모·법인 목록이 통째로 달라진다. 엑셀 반영 결과도 무효다.
  const box = $('import-report')
  if(box){ box.style.display = 'none'; box.innerHTML = '' }
  relatedSnapshot = null
  lastImport = null
  await refreshForYear({preserveAmounts: true})
})

function renderRelatedCompanies(companies){
  const tbody = document.querySelector('#related_table tbody')
  if(!tbody) return
  tbody.innerHTML = companies.map(name => `
    <tr data-company="${escapeHtml(name)}"><td>${escapeHtml(name)}</td><td><input class="ramt" type="number" min="0" value="0" placeholder="0"></td><td><input class="rex" type="number" min="0" value="0" placeholder="0"></td></tr>
  `).join('')
}

// --- 엑셀 업로드 -------------------------------------------------------------
// 서버가 파일을 읽어 거래처별 금액만 돌려준다. 표를 채우는 것은 여기서 한다.
// 서버는 아무것도 저장하지 않으므로, 사용자가 표를 확인하고 '확인'을 눌러야 계산된다.

let relatedSnapshot = null   // 업로드 직전 표 상태 — 되돌리기용
let lastImport = null        // 미매칭 거래처를 나중에 반영하기 위해 들고 있는다

function snapshotRelated(){
  const snap = {}
  document.querySelectorAll('#related_table tbody tr').forEach(tr=>{
    const input = tr.querySelector('.ramt')
    const ex = tr.querySelector('.rex')
    snap[tr.dataset.company || ''] = {amount: input ? input.value : '0', article10: ex ? ex.value : '0'}
  })
  return snap
}

// 값은 숫자(매출액만) 또는 {amount, article10} 둘 다 받는다. 스냅샷 되돌리기가 후자를 쓴다.
function applyRelatedAmounts(amounts, {reset = false} = {}){
  document.querySelectorAll('#related_table tbody tr').forEach(tr=>{
    const name = tr.dataset.company || ''
    const input = tr.querySelector('.ramt')
    const ex = tr.querySelector('.rex')
    if(!input) return
    if(reset){ input.value = 0; if(ex) ex.value = 0 }
    if(!Object.prototype.hasOwnProperty.call(amounts, name)) return
    const v = amounts[name]
    if(v !== null && typeof v === 'object'){
      input.value = v.amount ?? 0
      if(ex) ex.value = v.article10 ?? 0
    } else {
      input.value = v
    }
  })
}

// 법인명을 선택자에 끼워 넣지 않고 행을 훑어 비교한다. 이름에 따옴표·공백이 있어도 안전하고,
// 표를 그릴 때 쓴 dataset 값과 정확히 같은 문자열로 맞춰볼 수 있다.
function addRelatedAmount(company, amount, article10){
  const rows = Array.from(document.querySelectorAll('#related_table tbody tr'))
  const tr = rows.find(row => (row.dataset.company || '') === company)
  const input = tr && tr.querySelector('.ramt')
  if(!input) return false
  input.value = (Number(input.value) || 0) + amount
  const ex = tr.querySelector('.rex')
  if(ex && article10) ex.value = (Number(ex.value) || 0) + article10
  return true
}

function setImportStatus(msg){
  const el = $('import-status')
  if(el) el.textContent = msg
}

function showImportError(msg){
  const box = $('import-report')
  if(!box) return
  box.className = 'import-report error'
  box.style.display = 'block'
  box.innerHTML = `<div class="import-fail">엑셀을 읽지 못했습니다</div><div style="margin-top:6px">${escapeHtml(msg)}</div>`
}

function renderImportReport(result){
  const box = $('import-report')
  if(!box) return
  const stats = result.stats || {}
  const warnings = (result.warnings || [])
    .map(w => `<div class="import-warn">${escapeHtml(w)}</div>`).join('')

  // 미매칭은 버리지 않는다. 어느 법인으로 넣을지 사용자가 직접 고른다.
  const unmatched = result.unmatched || []
  const options = allCompanies
    .map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')
  const unmatchedBlock = unmatched.length ? `
    <div style="margin-top:12px">
      <strong style="font-size:13px">목록에 없는 거래처 ${unmatched.length}건</strong>
      <div class="hint" style="margin-top:4px">그대로 두면 계산에 들어가지 않습니다. 넣을 법인을 고른 뒤 아래 버튼을 누르세요.</div>
      <table class="unmatched-table">
        <thead><tr><th>파일의 거래처명</th><th style="text-align:right">매출액</th><th style="width:190px">연결할 법인</th></tr></thead>
        <tbody>
          ${unmatched.map((u, i) => `
            <tr data-unmatched-index="${i}">
              <td>${escapeHtml(u.name)}</td>
              <td class="amount">${formatNum(u.amount)}원</td>
              <td><select class="unmatched-target"><option value="">— 넣지 않음 —</option>${options}</select></td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div class="import-actions"><button type="button" id="apply-unmatched">선택한 거래처 표에 반영</button></div>
    </div>` : ''

  // 파일의 이름과 서버 법인명이 다른 건은 접어서 보여준다('기타' → '기타법인' 처럼
  // 서버가 이어준 것을 사용자가 확인할 수 있어야 한다).
  const a10Total = (result.stats && result.stats.article10_total) || 0
  const a10Block = a10Total
    ? `<div class="hint" style="margin-top:4px">제10항 과세제외액 <strong>${formatNum(a10Total)}원</strong>도 함께 넣었습니다.</div>`
    : ''
  const renamed = (result.matched || [])
    .filter(m => (m.sources || []).some(s => s !== m.company))
  const renamedBlock = renamed.length ? `
    <details style="margin-top:10px">
      <summary style="cursor:pointer;font-size:13px;color:var(--brand-dark)">파일과 이름이 다르게 연결된 ${renamed.length}건 확인</summary>
      <table class="unmatched-table">
        <thead><tr><th>파일의 거래처명</th><th>연결된 법인</th><th style="text-align:right">매출액</th></tr></thead>
        <tbody>
          ${renamed.map(m => `<tr>
            <td>${escapeHtml(m.sources.join(', '))}</td>
            <td>${escapeHtml(m.company)}</td>
            <td class="amount">${formatNum(m.amount)}원</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </details>` : ''

  box.className = 'import-report'
  box.style.display = 'block'
  box.innerHTML = `
    <h5>엑셀 반영 완료</h5>
    <div>거래처 <strong>${stats.matched_count || 0}건</strong>을 표에 넣었습니다. 합계 <strong>${formatNum(stats.matched_total || 0)}원</strong>.</div>
    <div class="hint" style="margin-top:4px">표 전체를 파일 내용으로 바꿨습니다. 파일에 없던 거래처는 0 입니다.</div>
    ${a10Block}
    ${warnings}
    ${renamedBlock}
    ${unmatchedBlock}
    <div class="import-actions"><button type="button" id="undo-import" class="secondary">업로드 전으로 되돌리기</button></div>
  `
}

document.getElementById('template-download')?.addEventListener('click', async ()=>{
  if(!token){ setImportStatus('로그인 후 이용할 수 있습니다.'); return }
  setImportStatus('양식을 준비하는 중…')
  try{
    // 거래처 목록은 연도마다 다를 수 있으므로 양식도 연도를 따라간다.
    const res = await fetch(`/api/related-sales/template${yearQuery()}`,
                            {headers:{Authorization:'Bearer '+token}})
    if(!res.ok) throw new Error(`서버 오류 (${res.status})`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = currentYear ? `특수관계자_세부매출_양식_${currentYear}.xlsx`
                             : '특수관계자_세부매출_양식.xlsx'
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    setImportStatus('양식을 내려받았습니다. B열 금액만 채워서 다시 올려주세요.')
  }catch(e){
    setImportStatus(`양식을 받지 못했습니다: ${e.message}`)
  }
})

document.getElementById('excel-upload-button')?.addEventListener('click', ()=>{
  if(!token){ setImportStatus('로그인 후 이용할 수 있습니다.'); return }
  $('excel-upload-input')?.click()
})

document.getElementById('excel-upload-input')?.addEventListener('change', async (e)=>{
  const file = e.target.files && e.target.files[0]
  // 같은 파일을 고쳐서 다시 올릴 수 있어야 하므로 값을 비워 change 가 또 걸리게 한다.
  e.target.value = ''
  if(!file) return
  setImportStatus(`${file.name} 읽는 중…`)
  const box = $('import-report')
  if(box) box.style.display = 'none'
  try{
    const form = new FormData()
    form.append('file', file)
    // Content-Type 은 직접 넣지 않는다. 브라우저가 multipart 경계값을 붙여야 한다.
    const res = await fetch(`/api/related-sales/import${yearQuery()}`, {
      method: 'POST', headers: {Authorization:'Bearer '+token}, body: form
    })
    // 413 은 nginx 가 백엔드에 닿기도 전에 막은 것이라 본문이 JSON 이 아니라 HTML 이다.
    // 그대로 두면 '서버 오류 (413)' 만 뜨고 사용자는 뭘 해야 할지 알 수 없다.
    if(res.status === 413){
      throw new Error('파일이 너무 커서 서버가 받지 못했습니다. 필요한 기간·거래처만 남겨 다시 올리거나 관리자에게 문의하세요.')
    }
    const data = await res.json().catch(()=>null)
    if(!res.ok) throw new Error((data && data.detail) || `서버 오류 (${res.status})`)

    relatedSnapshot = snapshotRelated()
    lastImport = data
    const amounts = {}
    ;(data.matched || []).forEach(m => { amounts[m.company] = {amount: m.amount, article10: m.article10 || 0} })
    applyRelatedAmounts(amounts, {reset: true})
    renderImportReport(data)
    setImportStatus(`${file.name} 반영됨`)
  }catch(err){
    showImportError(err.message || '알 수 없는 오류')
    setImportStatus('')
  }
})

// 리포트는 업로드할 때마다 다시 그려지므로 버튼에 직접 걸지 않고 위임한다.
document.getElementById('import-report')?.addEventListener('click', (e)=>{
  if(e.target && e.target.id === 'undo-import'){
    if(!relatedSnapshot) return
    applyRelatedAmounts(relatedSnapshot)
    relatedSnapshot = null
    lastImport = null
    const box = $('import-report')
    if(box){ box.style.display = 'none'; box.innerHTML = '' }
    setImportStatus('업로드 전 상태로 되돌렸습니다.')
    return
  }
  if(e.target && e.target.id === 'apply-unmatched'){
    const unmatched = (lastImport && lastImport.unmatched) || []
    let applied = 0
    document.querySelectorAll('#import-report tr[data-unmatched-index]').forEach(tr=>{
      const select = tr.querySelector('.unmatched-target')
      const target = select && select.value
      if(!target) return
      const item = unmatched[Number(tr.dataset.unmatchedIndex)]
      if(!item) return
      if(addRelatedAmount(target, item.amount)){
        applied += 1
        // 두 번 눌러 금액이 두 배가 되는 사고를 막는다.
        tr.remove()
      }
    })
    setImportStatus(applied ? `미매칭 ${applied}건을 표에 더했습니다.` : '연결할 법인을 먼저 고르세요.')
  }
})

$('evaluate').onclick = async ()=>{
  if($('form-error')) $('form-error').textContent = ''
  // validation
  try{
    const related = getRelatedFromTable()
    const company = $('company').value
    if(!company){ showError('법인을 선택하세요'); return }
    // ensure company matches logged-in user's company unless admin
    if(myCompany && myCompany.company !== 'admin' && company !== myCompany.company){ showError('자기 법인만 판정할 수 있습니다'); return }
    const operating_income = Number($('operating_income').value)
    const corporate_tax = Number($('corporate_tax').value)
    const total_sales = Number($('total_sales').value)
    if(Number.isNaN(operating_income) || Number.isNaN(corporate_tax) || Number.isNaN(total_sales)){
      showError('숫자 필드에 유효한 값을 입력하세요'); return
    }
    if(total_sales < 0 || operating_income < 0 || corporate_tax < 0){ showError('음수 값은 허용되지 않습니다'); return }

    const tax_adjustments = getTaxFromTable()

    const body = {
      company, year: currentYear,
      operating_income, corporate_tax, total_sales, related_sales: related, tax_adjustments,
      article10_exclusions: getArticle10FromTable(),
      dividend_income: getDividendFromTable(),
      distributable_income: Number($('distributable_income')?.value || 0)
    }
    const reviewPath = myCompany && myCompany.company === 'admin' ? '/api/admin/evaluate-review' : '/api/evaluate'
    const r = await post(reviewPath, body)
    if(r && typeof r === 'object' && r.company && r.reason) {
      // 기업 구분은 서버가 판정한 값(r.size)이 정본이다. 화면 선택값은 응답이 없을 때만 쓴다.
      lastReviewInput = {company, year: r.year || currentYear, companySize: r.size || $('company_size').value, operating_income, corporate_tax, total_sales, related, tax_adjustments}
      const isAdmin = myCompany && myCompany.company === 'admin'
      renderReport(r, {...lastReviewInput, isAdmin})
      $('rawdata-button').style.display = isAdmin ? 'inline-block' : 'none'
      // 결과가 생겨야 판정근거·시뮬레이션·연도비교를 열 수 있다.
      lastResult = r
      lastBody = body
      hasResult = true
      syncNav()
      resetSimulation()
      showPage('result-page')
    } else {
      showError('서버 응답을 확인하세요')
    }
  } catch(e){ showError(e.message || '서버 응답을 확인하세요'); }
}

$('back-to-input').onclick = ()=> showPage('input-page')

$('rawdata-button').onclick = ()=>{
  if(!myCompany || myCompany.company !== 'admin' || !lastReviewInput) return
  showPage('rawdata-page')
}

$('rawdata-back').onclick = ()=> showPage('result-page')

function renderRawData(input){
  const rows = Object.entries(input.related || {}).map(([name, amount]) => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${formatNum(amount)}원</td></tr>`).join('')
  const taxRows = Object.entries(input.tax_adjustments || {}).map(([name, amount]) => `<tr><td>${escapeHtml(name)}</td><td style="text-align:right">${formatNum(amount)}원</td></tr>`).join('')
  $('rawdata-content').innerHTML = `
    <div class="report-note"><strong>관리자 RAWDATA</strong><br>이번 검토 요청에 입력되어 서버로 전송된 원본 입력값입니다. 서버의 지분율·주주별 원본 데이터는 보안상 표시하지 않습니다.</div>
    <section class="report-section"><h3>기본정보</h3><table class="raw-table"><tbody>
      <tr><th>법인명</th><td>${escapeHtml(input.company)}</td></tr>
      <tr><th>기업 구분</th><td>${escapeHtml(input.companySize || '')}</td></tr>
      <tr><th>검토 연도</th><td>${escapeHtml(input.year || '')}</td></tr>
      <tr><th>총매출</th><td style="text-align:right">${formatNum(input.total_sales)}원</td></tr>
      <tr><th>영업이익</th><td style="text-align:right">${formatNum(input.operating_income)}원</td></tr>
      <tr><th>법인세 상당액</th><td style="text-align:right">${formatNum(input.corporate_tax)}원</td></tr>
    </tbody></table></section>
    <section class="report-section"><h3>특수관계자 세부매출 원본</h3><table class="raw-table"><thead><tr><th>거래처명</th><th>매출액</th></tr></thead><tbody>${rows || '<tr><td colspan="2">입력된 내역이 없습니다.</td></tr>'}</tbody></table></section>
    <section class="report-section"><h3>세무조정내역 원본</h3><table class="raw-table"><thead><tr><th>조정 항목</th><th>금액</th></tr></thead><tbody>${taxRows || '<tr><td colspan="2">입력된 내역이 없습니다.</td></tr>'}</tbody></table></section>
  `
}

$('result-back-to-input').onclick = ()=> $('back-to-input').click()

function formatNum(n){ if(n===undefined || n===null) return '—'; if(typeof n==='number') return n.toLocaleString(); try{ return Number(n).toLocaleString() }catch(e){ return String(n) }}

function renderReport(r, input){
  const el = $('result')
  const judgment = r.reason || r.judgement || r.summary || '판정 결과 없음'
  const isTaxable = Boolean(r.taxable || r.gift_tax_total > 0)
  const relatedTotal = Number(r.related_sales_total || 0)
  const relatedRatio = Number(r.related_sales_ratio || 0)
  const normalRatio = Number(r.normal_ratio || 0)
  const relatedRows = Object.entries(input.related || {}).map(([name, amount]) => `
    <tr><td>${escapeHtml(name)}</td><td class="amount">${formatNum(amount)}원</td></tr>`).join('')
  const taxRows = Object.entries(input.tax_adjustments || {}).map(([name, amount]) => `
    <tr><td>${escapeHtml(name)}</td><td class="amount">${formatNum(amount)}원</td></tr>`).join('')
  const emptyRow = '<tr><td colspan="2" class="muted">입력된 내역이 없습니다.</td></tr>'
  const pct = v => `${(Number(v) * 100).toFixed(2)}%`
  // ⑩·§18 은 주주 무관하게 100% 라 지분율 정보가 없으므로 금액을 그대로 보여준다.
  // ⑭ 지분율 상당액은 (금액 ÷ 매출액) 으로 지분율이 역산되므로 일반 응답에는 거래처별 값도
  // 합계도 오지 않는다. 범위(rate_min/max)와 합계는 관리자 응답에만 실린다.
  const exclusionList = r.exclusion_details || []
  const exclusionRows = exclusionList.map(d => {
    let rate, amount
    if(d.rate !== null && d.rate !== undefined){
      rate = pct(d.rate)
      amount = `${formatNum(d.excluded_sales)}원`
    } else if(d.rate_min !== undefined){
      rate = `${pct(d.rate_min)} ~ ${pct(d.rate_max)}`
      amount = `${formatNum(d.excluded_sales_min)}원 ~ ${formatNum(d.excluded_sales_max)}원`
    } else {
      rate = '<span class="muted">주주별 상이</span>'
      amount = '<span class="muted">비공개</span>'
    }
    return `<tr><td>${escapeHtml(d.counterparty)}</td><td class="amount">${formatNum(d.sales)}원</td><td>${escapeHtml(d.reason)}</td><td>${escapeHtml(d.article)}</td><td class="amount">${rate}</td><td class="amount">${amount}</td></tr>`
  }).join('')
  const hasRatioRows = exclusionList.some(d => d.rate === null || d.rate === undefined)
  // 합계도 관리자 전용이다. 일반 응답에 실으면 거래처를 1건만 넣어 호출하거나 요청을 쪼개
  // 차분을 내는 것만으로 (합계 ÷ 매출액) = 지배주주 지분율이 그대로 복원된다.
  const ratioTotalRow = !hasRatioRows ? ''
    : (input.isAdmin && r.ratio_exclusion_total_max !== undefined
      ? `<tr class="total-row"><th colspan="5">⑭ 지분율 상당액 합계</th><td class="amount">${formatNum(r.ratio_exclusion_total_min)}원 ~ ${formatNum(r.ratio_exclusion_total_max)}원</td></tr>`
      : `<tr class="total-row"><th colspan="5">⑭ 지분율 상당액 합계</th><td class="amount muted">비공개 (지분율 역산 방지)</td></tr>`)
  const emptyExclusionRow = '<tr><td colspan="6" class="muted">입력된 특수관계자 매출이 없습니다.</td></tr>'
  const taxTotal = Object.values(input.tax_adjustments || {}).reduce((sum, v) => sum + (Number(v) || 0), 0)
  const taxTotalRow = taxRows ? `<tr class="total-row"><th>합계 (영업이익 가감액)</th><td class="amount">${formatNum(taxTotal)}원</td></tr>` : ''
  const adminLogic = input.isAdmin ? `
    <section class="logic-box"><h3>관리자용 계산 로직 검토</h3>
      <ol>
        <li>선택한 법인의 기업 구분에 따라 정상 거래 비율과 보유 요건 기준을 서버에서 적용합니다.</li>
        <li>입력한 특수관계자 매출을 합산하고 총매출 대비 특수관계 매출 비율을 계산합니다.</li>
        <li>세무조정 후 영업이익과 법인세 상당액을 반영해 과세 검토 대상 금액을 산출합니다.</li>
        <li>서버에 보관된 지분·관계 데이터를 적용해 증여의제 금액을 계산합니다.</li>
        <li>증여의제 금액에 누진세율을 적용해 산출 증여세와 과세 여부를 판정합니다.</li>
      </ol>
      <div class="logic-formula"><strong>검토 산식 요약</strong><br>
        특수관계 매출 비율 = 특수관계 매출 합계 ÷ 총매출<br>
        증여의제 금액 = 세후 영업이익 × 조정 비율 × 보유 요건 반영값<br>
        산출 증여세 = 증여의제 금액(배당소득 공제 후)에 세율 및 누진공제 적용<br>
        납부 증여세 = 산출 증여세 − 신고세액공제 3% (10원 미만 절사)<br>
        <span class="muted">※ 아래 주주별 상세(실명·지분율)는 관리자 인증에서만 노출됩니다. 일반 사용자 화면과 RAWDATA 화면에는 표시되지 않습니다.</span>
      </div>
      <div class="report-section" style="overflow:auto"><h3>주주별 계산 상세</h3>
        <table class="report-table detail-table"><thead><tr><th>구분</th><th>지분율</th><th>과세제외매출</th><th>제외 후 특수관계 매출 비율</th><th>세후 영업이익</th><th>증여의제이익</th><th>배당소득 공제</th><th>산출 증여세</th><th>신고세액공제</th><th>납부 증여세</th><th>판정</th></tr></thead><tbody>
          ${(r.shareholder_details || []).map(detail => `<tr><td>${escapeHtml(detail.code)}</td><td class="amount">${(Number(detail.holding_ratio) * 100).toFixed(2)}%</td><td class="amount">${formatNum(detail.excluded_sales)}원</td><td class="amount">${(Number(detail.adjusted_related_ratio) * 100).toFixed(2)}%</td><td class="amount">${formatNum(detail.after_tax_operating_income)}원</td><td class="amount">${formatNum(detail.deemed_gift_income)}원</td><td class="amount">${formatNum(detail.dividend_deduction || 0)}원</td><td class="amount">${formatNum(detail.gift_tax)}원</td><td class="amount">${formatNum(detail.filing_credit || 0)}원</td><td class="amount"><strong>${formatNum(detail.gift_tax_payable || 0)}원</strong></td><td>${detail.taxable ? '<span class="report-status yes">대상</span>' : '<span class="report-status no">비대상</span>'}</td></tr>`).join('')}
          <tr class="total-row"><th colspan="5">총합</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td><td class="amount">${formatNum(r.dividend_deduction_total || 0)}원</td><td class="amount">${formatNum(r.gift_tax_total)}원</td><td class="amount">${formatNum(r.filing_credit_total || 0)}원</td><td class="amount"><strong>${formatNum(r.gift_tax_payable_total || 0)}원</strong></td><td></td></tr>
        </tbody></table>
        <div class="hint">관리자 인증에서만 표시되는 상세값입니다.</div>
      </div>
    </section>` : ''

  el.innerHTML = `
    <div class="report-note"><span class="report-status ${isTaxable ? 'yes' : 'no'}">${isTaxable ? '과세대상' : '해당없음'}</span><div style="margin-top:8px">${escapeHtml(judgment)}</div></div>

    <section class="report-section"><h3>1. 기본정보</h3>
      <table class="report-table"><tbody>
        <tr><th>법인명</th><td>${escapeHtml(input.company)}</td></tr>
        <tr><th>기업 구분</th><td>${escapeHtml(input.companySize || '미입력')}</td></tr>
        <tr><th>검토 연도</th><td>${escapeHtml(r.year || '')}${r.data_as_of ? ` <span class="muted">(${escapeHtml(r.data_as_of)})</span>` : ''}</td></tr>
        <tr><th>총매출</th><td class="amount">${formatNum(input.total_sales)}원</td></tr>
        <tr><th>영업이익</th><td class="amount">${formatNum(input.operating_income)}원</td></tr>
        <tr><th>법인세 상당액</th><td class="amount">${formatNum(input.corporate_tax)}원</td></tr>
      </tbody></table>
    </section>

    ${(r.notices || []).length ? `<div class="report-notice"><strong>확인이 필요합니다</strong><ul>${r.notices.map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul></div>` : ''}

    <section class="report-section"><h3>2. 판정 요건 및 계산 결과</h3>
      <table class="report-table"><tbody>
        <tr><th>특수관계자 매출 합계</th><td class="amount">${formatNum(relatedTotal)}원</td></tr>
        <tr><th>특수관계자 매출 비율</th><td class="amount">${(relatedRatio * 100).toFixed(1)}%</td></tr>
        <tr><th>정상 거래 비율</th><td class="amount">${(normalRatio * 100).toFixed(1)}%</td></tr>
        ${input.isAdmin ? `<tr><th>과세제외매출(공통)¹</th><td class="amount">${formatNum(r.excluded_sales_common)}원</td></tr>
        <tr><th>과세제외매출(계산 범위)²</th><td class="amount">${formatNum(r.excluded_sales_min)}원 ~ ${formatNum(r.excluded_sales_max)}원</td></tr>
        <tr><th>제외 후 특수관계 매출 비율</th><td class="amount">${(r.adjusted_related_ratio_min * 100).toFixed(1)}% ~ ${(r.adjusted_related_ratio_max * 100).toFixed(1)}%</td></tr>` : ''}
        <tr><th>증여의제 금액</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td></tr>
        ${r.dividend_deduction_total ? `<tr><th>배당소득 공제</th><td class="amount">-${formatNum(r.dividend_deduction_total)}원</td></tr>` : ''}
        <tr><th>산출 증여세</th><td class="amount">${formatNum(r.gift_tax_total)}원</td></tr>
        <tr><th>신고세액공제 (3%)</th><td class="amount">-${formatNum(r.filing_credit_total || 0)}원</td></tr>
        <tr><th>납부 증여세</th><td class="amount"><strong>${formatNum(r.gift_tax_payable_total || 0)}원</strong></td></tr>
      </tbody></table>
      ${input.isAdmin ? '<div class="hint">¹ 제10항 기준으로 공통 제외된 매출입니다. ² 서버의 민감한 지분 계산을 집계한 범위이며 원본 비율은 표시하지 않습니다.</div>' : ''}
    </section>

    <section class="report-section"><h3>3. 특수관계자 세부매출</h3>
      <table class="report-table"><thead><tr><th>거래처명</th><th>매출액</th></tr></thead><tbody>${relatedRows || emptyRow}</tbody></table>
    </section>

    <section class="report-section"><h3>4. 과세제외 내역</h3>
      <div style="overflow:auto">
        <table class="report-table exclusion-table"><thead><tr><th>거래처명</th><th>매출액</th><th>과세제외 사유</th><th>적용 조문</th><th>적용률</th><th>과세제외매출액</th></tr></thead><tbody>${exclusionRows || emptyExclusionRow}${ratioTotalRow}</tbody></table>
      </div>
      <div class="hint">⑩ 기본 과세제외를 먼저 판정하고, 해당하지 않는 거래처만 ⑭ 추가 과세제외를 적용합니다. 사유가 겹치면 합산하지 않고 과세제외금액이 가장 큰 하나만 적용합니다. ⑭ 지분율 상당액은 지배주주마다 적용률이 달라 ${input.isAdmin ? '최소~최대 범위로 표시하며, 주주별 상세는 아래 관리자 검토 항목을 참고하세요.' : '거래처별 값 대신 합계 범위로 표시합니다.'}</div>
    </section>

    <section class="report-section"><h3>5. 세무조정내역</h3>
      <table class="report-table"><thead><tr><th>조정 항목</th><th>금액</th></tr></thead><tbody>${taxRows || emptyRow}${taxTotalRow}</tbody></table>
      <div class="hint">세후영업이익 = 영업이익 ± 세무조정금액 − 법인세 상당액</div>
    </section>

    ${adminLogic}
  `
}

// 속성값 안에도 삽입되므로(data-company="...") 따옴표까지 이스케이프한다.
function escapeHtml(s){
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;')
}

// ═══════════════════════════════════════════════════════════════════════════
// 페이지 전환
// ═══════════════════════════════════════════════════════════════════════════
// 종전에는 페이지마다 style.display 를 직접 만졌다. 페이지가 8개가 되면서
// '어디선가 안 감춘 페이지'가 겹쳐 보이는 사고가 나기 쉬워 한 곳으로 모았다.
// display 를 지우지 않고 [hidden] 으로 감춘다 — #input-page 는 grid 라
// 'block' 으로 되돌리면 사이드 가이드가 본문 아래로 떨어진다.

const PAGES = ['input-page', 'result-page', 'criteria-page', 'simulate-page',
               'compare-page', 'bulk-page', 'dashboard-page', 'rawdata-page']

let lastResult = null    // 마지막 판정 응답
let lastBody = null      // 그때 서버로 보낸 요청 본문 (시뮬레이션·연도비교가 다시 쓴다)
let hasResult = false

function isAdminUser(){ return Boolean(myCompany && myCompany.company === 'admin') }

function syncNav(){
  const nav = $('nav')
  if(!nav) return
  nav.querySelectorAll('button[data-page]').forEach(b=>{
    if(b.hasAttribute('data-admin')) b.hidden = !isAdminUser()
    // 결과가 없으면 판정근거·시뮬레이션·연도비교는 보여줄 것이 없다.
    if(b.dataset.needs === 'result') b.disabled = !hasResult
  })
}

function showPage(id){
  PAGES.forEach(p => { const el = $(p); if(el) el.hidden = (p !== id) })
  $('nav')?.querySelectorAll('button[data-page]').forEach(b=>{
    if(b.dataset.page === id) b.setAttribute('aria-current', 'page')
    else b.removeAttribute('aria-current')
  })
  if(id === 'input-page' && $('form-error')) $('form-error').textContent = ''
  if(id === 'criteria-page') renderCriteria()
  if(id === 'simulate-page') renderSimulation()
  if(id === 'compare-page') runCompare()
  if(id === 'bulk-page') renderBulk()
  if(id === 'dashboard-page') renderDashboard()
  if(id === 'rawdata-page' && lastReviewInput) renderRawData(lastReviewInput)
  window.scrollTo(0, 0)
}

document.addEventListener('click', (e)=>{
  const nav = e.target.closest && e.target.closest('#nav button[data-page]')
  if(nav && !nav.disabled){ showPage(nav.dataset.page); return }
  const goto = e.target.closest && e.target.closest('[data-goto]')
  if(goto) showPage(goto.dataset.goto)
})


// ═══════════════════════════════════════════════════════════════════════════
// 공통 표시 헬퍼
// ═══════════════════════════════════════════════════════════════════════════

function pctStr(v, digits = 2){
  if(v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function emptyBox(msg){ return `<div class="empty">${escapeHtml(msg)}</div>` }

function tile(label, value, sub, tone){
  return `<div class="tile ${tone || ''}">
    <div class="tile-label">${escapeHtml(label)}</div>
    <div class="tile-value">${value}</div>
    ${sub ? `<div class="tile-sub">${sub}</div>` : ''}
  </div>`
}

// 판정비율 하나를 문턱(정상거래비율)과 견주는 그림.
// 축이 하나뿐이고, 막대 색은 과세/해당없음 상태만 나타내며 수치는 항상 글자로 같이 적는다.
function meterHtml(actual, threshold, opts){
  const o = opts || {}
  const a = Number(actual) || 0
  const t = Number(threshold) || 0
  // 문턱이 늘 눈에 보이도록 둘 중 큰 값에 여유를 둔 눈금을 쓴다.
  const scale = Math.max(a, t) * 1.25 || 1
  const w = Math.max(0, Math.min(100, (a / scale) * 100))
  const tp = Math.max(0, Math.min(100, (t / scale) * 100))
  const over = a > t
  return `<div class="meter ${over ? 'over' : ''}">
    <div class="meter-track has-thr">
      <div class="meter-fill" style="width:${w.toFixed(2)}%"></div>
      <div class="meter-thr" style="left:${tp.toFixed(2)}%"></div>
    </div>
    <div class="meter-legend">
      <span>${escapeHtml(o.label || '판정비율')} <b>${pctStr(a)}</b></span>
      <span class="thr-key">${escapeHtml(o.thresholdLabel || '정상거래비율')} <b>${pctStr(t, 0)}</b></span>
    </div>
  </div>`
}

function statusTag(taxable){
  return taxable
    ? '<span class="tag bad">과세대상</span>'
    : '<span class="tag ok">해당없음</span>'
}

function criteriaByKey(r){
  const out = {}
  ;(r && r.criteria || []).forEach(c => { out[c.key] = c })
  return out
}

// CSV 는 Excel 이 BOM 없이는 ANSI 로 열어 한글이 깨진다.
function downloadCsv(filename, rows){
  const cell = s => `"${String(s === null || s === undefined ? '' : s).replace(/"/g, '""')}"`
  const csv = rows.map(r => r.map(cell).join(',')).join('\n')
  const blob = new Blob([String.fromCharCode(0xFEFF) + csv], {type: 'text/csv;charset=utf-8;'})
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  URL.revokeObjectURL(url)
}


// ═══════════════════════════════════════════════════════════════════════════
// 1. 과세요건 판정 근거
// ═══════════════════════════════════════════════════════════════════════════
// reason 한 문장으로는 '세 요건 중 어디서 걸렸는지'를 못 보여준다.
// 요건별 판정은 서버(calc._criteria)가 실제 판정과 같은 비교식으로 내려준다 —
// 화면에서 다시 비교하지 않는다. 여기서 식을 새로 쓰면 설명과 세액이 갈린다.

function renderCriteria(){
  const el = $('criteria-content')
  if(!el) return
  if(!lastResult){ el.innerHTML = emptyBox('먼저 입력 화면에서 검토를 실행하세요.'); return }
  const r = lastResult
  const by = criteriaByKey(r)
  const order = ['income', 'ratio', 'holding']
  const cards = order.filter(k => by[k]).map((k, i) => {
    const c = by[k]
    const extra = k === 'ratio'
      ? `<div class="crit-meter">${meterHtml(c.actual, c.threshold)}</div>`
      : ''
    return `<div class="crit ${c.passed ? 'pass' : 'fail'}">
      <div class="crit-mark">${c.passed ? '✓' : (i + 1)}</div>
      <div class="crit-body">
        <div class="crit-label">요건 ${i + 1}. ${escapeHtml(c.label)}</div>
        <div class="crit-detail">${escapeHtml(c.detail)}</div>
        ${extra}
      </div>
      <span class="crit-state">${c.passed ? '충족' : '미충족'}</span>
    </div>`
  }).join('')

  const ratio = by.ratio || {}
  // 문턱까지 얼마나 남았는지 / 얼마나 넘었는지. 실무에서 가장 먼저 보는 숫자다.
  const marginTile = ratio.passed
    ? tile('문턱 초과분', pctStr(ratio.gap), '이만큼 낮춰야 문턱 아래로 내려갑니다', 'bad')
    : tile('문턱까지 여유', pctStr(-(ratio.gap || 0)),
           ratio.headroom !== null && ratio.headroom !== undefined
             ? `특수관계자 매출 ${formatNum(ratio.headroom)}원까지` : '', 'ok')

  // 판정비율과 특관매출비율이 다른 이유는 ⑩ 과세제외다. 이걸 안 보여주면
  // '매출 비율이 40%인데 왜 판정비율은 3%냐'는 질문이 반드시 나온다.
  const a10 = Number(r.article10_total || 0)
  const exclusionNote = a10 > 0 ? `
    <section class="report-section"><h3>판정비율이 매출비율과 다른 이유</h3>
      <table class="report-table"><tbody>
        <tr><th>특수관계자 매출 합계</th><td class="amount">${formatNum(r.related_sales_total)}원 <span class="muted">(${pctStr(r.related_sales_ratio)})</span></td></tr>
        <tr><th>− 제10항 과세제외</th><td class="amount">${formatNum(a10)}원</td></tr>
        <tr><th>= 판정 대상 매출</th><td class="amount"><strong>${formatNum(Number(r.related_sales_total || 0) - a10)}원</strong> <span class="muted">(${pctStr(r.taxation_ratio)})</span></td></tr>
      </tbody></table>
      <div class="hint">과세요건 판정에는 ⑩ 만 뺀 비율을 씁니다. ⑭ 지분율 상당액은 세액 계산에만 반영되며 판정비율은 낮추지 않습니다.</div>
    </section>` : ''

  el.innerHTML = `
    <div class="report-note">
      <span class="report-status ${r.taxable ? 'yes' : 'no'}">${r.taxable ? '과세대상' : '해당없음'}</span>
      <div style="margin-top:8px">${escapeHtml(r.reason || '')}</div>
    </div>

    <section class="report-section"><h3>한눈에 보기</h3>
      <div class="tiles">
        ${tile('법인', escapeHtml(r.company), escapeHtml(`${r.size || ''} · ${r.year || ''}년`))}
        ${tile('판정비율', pctStr(r.taxation_ratio), `정상거래비율 ${pctStr(r.normal_ratio, 0)}`)}
        ${marginTile}
        ${tile('납부 증여세', `${formatNum(r.gift_tax_payable_total || 0)}원`,
               `산출 ${formatNum(r.gift_tax_total || 0)}원`, r.taxable ? 'bad' : '')}
      </div>
    </section>

    <section class="report-section"><h3>요건별 판정</h3>
      <div class="criteria-list">${cards}</div>
      <div class="hint">세 요건을 <strong>모두</strong> 충족해야 과세대상입니다. 하나라도 미충족이면 해당없음입니다.</div>
    </section>

    ${exclusionNote}

    ${(r.notices || []).length ? `<div class="report-notice" style="margin-top:22px"><strong>확인이 필요합니다</strong><ul>${r.notices.map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul></div>` : ''}
  `
}


// ═══════════════════════════════════════════════════════════════════════════
// 2. 시뮬레이션 (What-if)
// ═══════════════════════════════════════════════════════════════════════════
// 마지막 검토 입력을 복제해 조정한다. 지분율은 건드리지 않는다 —
// 서버가 지분 데이터에서 판정하는 값이라 화면에서 바꿀 수 있으면 안 된다.
// 특수관계자 매출은 거래처별로 다시 입력받는 대신 합계를 비례 조정한다
// (거래처 구성이 아니라 규모가 세액을 좌우한다).

let simState = null
let simTimer = null
let simBaseResult = null

const SIM_FIELDS = [
  {key: 'total_sales', label: '총매출', max: 2},
  {key: 'related_total', label: '특수관계자 매출 합계', max: 2},
  {key: 'operating_income', label: '영업이익', max: 2},
  {key: 'corporate_tax', label: '법인세 상당액', max: 2},
]

function resetSimulation(){
  simState = null
  simBaseResult = null
}

function simBase(){
  const related = (lastBody && lastBody.related_sales) || {}
  return {
    total_sales: Number(lastBody.total_sales) || 0,
    related_total: Object.values(related).reduce((s, v) => s + (Number(v) || 0), 0),
    operating_income: Number(lastBody.operating_income) || 0,
    corporate_tax: Number(lastBody.corporate_tax) || 0,
  }
}

function renderSimulation(){
  const el = $('simulate-content')
  if(!el) return
  if(!lastBody || !lastResult){ el.innerHTML = emptyBox('먼저 입력 화면에서 검토를 실행하세요.'); return }
  if(!simState){
    simState = simBase()
    simBaseResult = lastResult
  }
  const base = simBase()
  const controls = SIM_FIELDS.map(f=>{
    const v = simState[f.key]
    const b = base[f.key]
    const max = Math.max(Math.round(b * f.max), 1)
    return `<div class="sim-field">
      <label for="sim-${f.key}">${escapeHtml(f.label)}</label>
      <input id="sim-${f.key}" class="sim-num" data-key="${f.key}" type="number" min="0" value="${v}">
      <div class="sim-row" style="margin-top:7px">
        <input class="sim-range" data-key="${f.key}" type="range" min="0" max="${max}"
               step="${Math.max(1, Math.round(max / 200))}" value="${Math.min(v, max)}">
        <span class="sim-delta ${deltaClass(v, b)}">${deltaLabel(v, b)}</span>
      </div>
      <div class="hint">원래 값 ${formatNum(b)}원</div>
    </div>`
  }).join('')

  el.innerHTML = `
    <div class="sim-grid">
      <div>
        <p class="sec-t">조정할 값</p>
        ${controls}
        <div class="hint">지분율·기업규모·과세제외 규칙은 서버 데이터를 그대로 씁니다. 화면에서 바꿀 수 없습니다.</div>
      </div>
      <div id="sim-output">${emptyBox('계산 중…')}</div>
    </div>`
  runSimulation()
}

function deltaClass(v, b){ if(v === b) return 'same'; return v > b ? 'up' : 'down' }
function deltaLabel(v, b){
  if(v === b) return '원래 값'
  if(!b) return v > 0 ? '신규' : ''
  const pct = ((v - b) / Math.abs(b)) * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
}

document.addEventListener('input', (e)=>{
  const t = e.target
  if(!t || !simState) return
  if(t.classList.contains('sim-num') || t.classList.contains('sim-range')){
    const key = t.dataset.key
    const value = Math.max(0, Math.round(Number(t.value) || 0))
    simState[key] = value
    // 숫자칸과 슬라이더를 서로 맞춘다.
    document.querySelectorAll(`.sim-num[data-key="${key}"]`).forEach(x => { if(x !== t) x.value = value })
    document.querySelectorAll(`.sim-range[data-key="${key}"]`).forEach(x => { if(x !== t) x.value = value })
    const base = simBase()
    const badge = t.closest('.sim-field')?.querySelector('.sim-delta')
    if(badge){
      badge.textContent = deltaLabel(value, base[key])
      badge.className = `sim-delta ${deltaClass(value, base[key])}`
    }
    clearTimeout(simTimer)
    simTimer = setTimeout(runSimulation, 250)
  }
})

$('sim-reset')?.addEventListener('click', ()=>{
  simState = simBase()
  renderSimulation()
})

// 특수관계자 매출 합계를 바꾸면 거래처별 금액을 같은 비율로 늘리고 줄인다.
// ⑩ 과세제외액도 같이 움직여야 판정비율이 뒤틀리지 않는다.
function scaleMap(map, factor){
  const out = {}
  Object.entries(map || {}).forEach(([k, v]) => { out[k] = Math.round((Number(v) || 0) * factor) })
  return out
}

async function runSimulation(){
  const out = $('sim-output')
  if(!out || !simState || !lastBody) return
  const base = simBase()
  const factor = base.related_total ? (simState.related_total / base.related_total) : 0
  const body = {
    ...lastBody,
    total_sales: simState.total_sales,
    operating_income: simState.operating_income,
    corporate_tax: simState.corporate_tax,
    related_sales: base.related_total
      ? scaleMap(lastBody.related_sales, factor)
      : (lastBody.related_sales || {}),
    article10_exclusions: base.related_total
      ? scaleMap(lastBody.article10_exclusions, factor)
      : (lastBody.article10_exclusions || {}),
  }
  try{
    // 시뮬레이션은 늘 공개 응답으로 충분하다. 관리자 상세는 결과 화면에서 본다.
    const r = await post('/api/evaluate', body)
    renderSimOutput(r)
  }catch(err){
    out.innerHTML = `<div class="import-report error">${escapeHtml(err.message || '계산에 실패했습니다')}</div>`
  }
}

function renderSimOutput(r){
  const out = $('sim-output')
  if(!out) return
  const b = simBaseResult || {}
  const by = criteriaByKey(r)
  const ratio = by.ratio || {}
  const payable = Number(r.gift_tax_payable_total || 0)
  const basePayable = Number(b.gift_tax_payable_total || 0)
  const diff = payable - basePayable
  const diffLabel = diff === 0
    ? '원래 값과 같습니다'
    : `${diff > 0 ? '+' : '−'}${formatNum(Math.abs(diff))}원 ${diff > 0 ? '증가' : '감소'}`

  out.innerHTML = `
    <p class="sec-t">시뮬레이션 결과</p>
    <div class="hero">
      <div class="hero-label">납부 증여세 <span class="tag ${r.taxable ? 'bad' : 'ok'}" style="margin-left:6px">${r.taxable ? '과세대상' : '해당없음'}</span></div>
      <div class="hero-value" style="color:${r.taxable ? 'var(--bad)' : 'var(--ok)'}">${formatNum(payable)}원</div>
      <div class="tile-sub">${escapeHtml(diffLabel)} <span class="muted">(원래 ${formatNum(basePayable)}원)</span></div>
    </div>

    <div style="margin-top:18px">${meterHtml(r.taxation_ratio, r.normal_ratio)}</div>

    <table class="report-table" style="margin-top:18px"><tbody>
      <tr><th>판정 대상 매출</th><td class="amount">${formatNum(Number(r.related_sales_total || 0) - Number(r.article10_total || 0))}원</td></tr>
      <tr><th>판정비율</th><td class="amount">${pctStr(r.taxation_ratio)}</td></tr>
      <tr><th>정상거래비율</th><td class="amount">${pctStr(r.normal_ratio, 0)}</td></tr>
      <tr><th>${ratio.passed ? '문턱 초과분' : '문턱까지 여유'}</th><td class="amount">${pctStr(Math.abs(ratio.gap || 0))}${(!ratio.passed && ratio.headroom != null) ? ` <span class="muted">(매출 ${formatNum(ratio.headroom)}원)</span>` : ''}</td></tr>
      <tr><th>증여의제 금액</th><td class="amount">${formatNum(r.deemed_gift_total)}원</td></tr>
      <tr><th>산출 증여세</th><td class="amount">${formatNum(r.gift_tax_total)}원</td></tr>
    </tbody></table>
    <div class="hint">${escapeHtml(r.reason || '')}</div>
    <div class="hint" style="margin-top:10px">이 화면의 값은 <strong>저장되지 않습니다.</strong> 신고에 쓸 숫자는 입력 화면에서 다시 검토하세요.</div>
  `
}


// ═══════════════════════════════════════════════════════════════════════════
// 3. 연도 비교
// ═══════════════════════════════════════════════════════════════════════════
// 같은 입력을 연도별 지분·규모·세율에 각각 통과시킨다.
// 실제 연도별 재무수치 차이는 반영되지 않는다 — 화면에도 그렇게 적는다.

let compareToken = 0

async function runCompare(){
  const el = $('compare-content')
  if(!el) return
  if(!lastBody){ el.innerHTML = emptyBox('먼저 입력 화면에서 검토를 실행하세요.'); return }
  const years = Object.keys(yearAsOf)
  if(years.length <= 1){
    el.innerHTML = emptyBox('비교할 연도가 하나뿐입니다. 서버에 다른 연도 데이터가 있어야 합니다.')
    return
  }
  el.innerHTML = emptyBox('연도별로 계산하는 중…')
  const run = ++compareToken

  const rows = await Promise.all(years.map(async year => {
    try{
      return {year, r: await post('/api/evaluate', {...lastBody, year})}
    }catch(err){
      // 그 해에 없는 법인(신설·청산)이면 400 이 온다. 조용히 빼지 않고 사유를 적는다.
      return {year, error: err.message || '계산할 수 없습니다'}
    }
  }))
  if(run !== compareToken) return   // 그 사이 다른 페이지로 갔다

  const ok = rows.filter(x => x.r)
  const baseline = ok.length ? ok[0].r : null
  const body = rows.map(x=>{
    if(x.error){
      return `<tr><td><strong>${escapeHtml(x.year)}</strong></td>
        <td colspan="7" class="muted">${escapeHtml(x.error)}</td></tr>`
    }
    const r = x.r
    const by = criteriaByKey(r)
    const ratio = by.ratio || {}
    const delta = baseline && r !== baseline
      ? Number(r.gift_tax_payable_total || 0) - Number(baseline.gift_tax_payable_total || 0)
      : 0
    const deltaCell = (baseline && r === baseline)
      ? '<span class="muted">기준</span>'
      : (delta === 0 ? '<span class="muted">동일</span>'
        : `<span class="sim-delta ${delta > 0 ? 'up' : 'down'}">${delta > 0 ? '+' : '−'}${formatNum(Math.abs(delta))}원</span>`)
    return `<tr>
      <td><strong>${escapeHtml(r.year)}</strong><div class="row-note">${escapeHtml(r.data_as_of || '')}</div></td>
      <td>${escapeHtml(r.size || '')}</td>
      <td class="amount">${pctStr(r.taxation_ratio)}</td>
      <td class="amount">${pctStr(r.normal_ratio, 0)}</td>
      <td class="amount">${ratio.passed ? '+' : '−'}${pctStr(Math.abs(ratio.gap || 0))}</td>
      <td>${statusTag(r.taxable)}</td>
      <td class="amount">${formatNum(r.gift_tax_payable_total || 0)}원</td>
      <td class="amount">${deltaCell}</td>
    </tr>`
  }).join('')

  const changed = ok.length > 1 && new Set(ok.map(x => x.r.size)).size > 1
  el.innerHTML = `
    <div class="table-wrap">
      <table class="wide-table">
        <thead><tr>
          <th>연도</th><th>기업구분</th><th class="amount">판정비율</th><th class="amount">정상거래비율</th>
          <th class="amount">문턱 대비</th><th>판정</th><th class="amount">납부 증여세</th><th class="amount">기준연도 대비</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
    <div class="report-note" style="margin-top:16px">
      <strong>이 표가 보여주는 것</strong><br>
      ${escapeHtml(lastBody.company)}의 <strong>같은 재무수치</strong>를 연도별 지분율·기업규모·세율에 각각 통과시킨 결과입니다.
      연도 간 차이는 <strong>지분·규모·세율 변화</strong>에서만 옵니다.
      ${changed ? '<br><strong>기업구분이 연도마다 다릅니다.</strong> 정상거래비율 문턱 자체가 달라지므로 비율만 비교하면 오해할 수 있습니다.' : ''}
      <br>실제 연도별 매출·영업이익으로 비교하려면 입력 화면에서 연도를 바꿔 각각 검토하세요.
    </div>`
}


// ═══════════════════════════════════════════════════════════════════════════
// 4. 통합본 일괄 판정 (관리자)
// ═══════════════════════════════════════════════════════════════════════════
// 파싱과 계산을 나눠 둔 이유: 통합본에는 법인세가 없고, 아직 안 채워진 법인이
// 섞여 있다. 사용자가 표를 보고 보정한 뒤에 계산해야 한다.
// 서버는 어느 단계에서도 저장하지 않는다 — 새로고침하면 다시 올려야 한다.

let bulkParsed = null
let bulkResults = null
let bulkTaxInputs = {}   // {법인: 법인세}

$('bulk-upload-button')?.addEventListener('click', ()=> $('bulk-upload-input')?.click())

$('bulk-upload-input')?.addEventListener('change', async (e)=>{
  const file = e.target.files && e.target.files[0]
  e.target.value = ''
  if(!file) return
  const el = $('bulk-content')
  el.innerHTML = emptyBox(`${file.name} 읽는 중…`)
  const form = new FormData()
  form.append('file', file)
  try{
    const res = await fetch(`/api/admin/bulk/parse${yearQuery()}`, {
      method: 'POST',
      headers: token ? {Authorization: 'Bearer ' + token} : {},
      body: form,
    })
    const data = await res.json().catch(()=> null)
    if(!res.ok) throw new Error((data && data.detail) || `서버 오류 (${res.status})`)
    bulkParsed = data
    bulkParsed.filename = file.name
    bulkResults = null
    bulkTaxInputs = {}
    // 파일에 법인세가 있으면 그 값으로 시작한다.
    data.sheets.forEach(s => { if(s.company && s.corporate_tax != null) bulkTaxInputs[s.company] = s.corporate_tax })
    renderBulk()
  }catch(err){
    el.innerHTML = `<div class="import-report error">${escapeHtml(err.message || '파일을 읽지 못했습니다')}</div>`
  }
})

const BULK_STATUS_TAG = {
  'ok': '<span class="tag ok">판정 가능</span>',
  '확인필요': '<span class="tag warn">확인 필요</span>',
  '입력대기': '<span class="tag mute">입력 대기</span>',
  '미매칭': '<span class="tag bad">법인 미매칭</span>',
  '건너뜀': '<span class="tag mute">법인 시트 아님</span>',
}

function renderBulk(){
  const el = $('bulk-content')
  if(!el) return
  if(!bulkParsed){
    el.innerHTML = emptyBox('법인마다 시트가 하나씩 있는 통합본(.xlsx)을 올리세요. 시트에서 법인명·기업구분·총매출액·영업이익과 특수관계자 매출 상세표를 읽습니다.')
    return
  }
  const p = bulkParsed
  const rows = p.sheets.map((s, i)=>{
    const selectable = s.status === 'ok' || s.status === '확인필요'
    const tax = bulkTaxInputs[s.company]
    return `<tr data-sheet-index="${i}">
      <td>${selectable ? `<input type="checkbox" class="bulk-pick" ${s.status === 'ok' ? 'checked' : ''} style="min-height:0;width:auto">` : ''}</td>
      <td><strong>${escapeHtml(s.company || s.excel_name)}</strong>
        <div class="row-note">시트 ${escapeHtml(s.sheet)}${s.size_app ? ` · ${escapeHtml(s.size_app)}` : ''}</div></td>
      <td>${BULK_STATUS_TAG[s.status] || escapeHtml(s.status)}</td>
      <td class="amount">${s.total_sales == null ? '<span class="muted">—</span>' : formatNum(s.total_sales) + '원'}</td>
      <td class="amount">${s.operating_income == null ? '<span class="muted">—</span>' : formatNum(s.operating_income) + '원'}</td>
      <td class="amount">${formatNum(s.related_total)}원<div class="row-note">거래처 ${s.counterparty_count}곳</div></td>
      <td class="amount">${s.foreign_sales_total
        ? `<span class="muted">${formatNum(s.foreign_sales_total)}원</span><div class="row-note">위 매출에서 이미 차감됨</div>`
        : '<span class="muted">0원</span>'}</td>
      <td class="amount">${selectable
        ? `<input type="number" min="0" class="bulk-tax" data-company="${escapeHtml(s.company)}" value="${tax != null ? tax : 0}">`
        : '<span class="muted">—</span>'}</td>
      <td>${s.warnings.length
        ? `<div class="row-note">${s.warnings.map(w => escapeHtml(w)).join('<br>')}</div>`
        : '<span class="muted">—</span>'}</td>
    </tr>`
  }).join('')

  const missing = p.missing_companies || []
  el.innerHTML = `
    <div class="tiles" style="margin-bottom:18px">
      ${tile('읽은 시트', p.stats.sheets_read, escapeHtml(p.filename || ''))}
      ${tile('판정 가능', p.stats.ready, `${p.year}년 데이터 기준`, 'ok')}
      ${tile('보류', p.stats.pending, '입력 대기·확인 필요')}
      ${tile('법인 시트 아님', p.stats.skipped || 0, '요약·분류 시트 등')}
      ${tile('시트 없음', p.stats.missing, '통합본에 시트가 없는 법인')}
    </div>

    ${(p.warnings || []).length ? `<div class="report-notice"><strong>파일 전체 안내</strong><ul>${p.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('')}</ul></div>` : ''}

    <div class="report-notice">
      <strong>법인세 상당액을 확인하세요</strong>
      통합본에는 법인세 항목이 없습니다. 0 으로 두면 세후영업이익이 그만큼 커져 <b>세액이 과대 계산</b>됩니다.
    </div>

    <div class="table-wrap">
      <table class="wide-table">
        <thead><tr>
          <th style="width:34px"></th><th>법인</th><th>상태</th><th class="amount">총매출</th>
          <th class="amount">영업이익</th><th class="amount">특수관계자 매출</th><th class="amount">해외매출</th>
          <th class="amount" style="width:130px">법인세 상당액</th><th style="width:280px">확인 사항</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>

    <div class="btn-row">
      <button type="button" id="bulk-run">선택한 법인 일괄 판정</button>
      <button type="button" id="bulk-pick-all" class="secondary">전체 선택</button>
      <span class="hint">서버는 파일도 입력값도 저장하지 않습니다. 새로고침하면 다시 올려야 합니다.</span>
    </div>
    <div id="bulk-error" class="form-error"></div>

    ${missing.length ? `<section class="report-section"><h3>통합본에 시트가 없는 법인 (${missing.length}곳)</h3>
      <div class="hint">${missing.map(m => escapeHtml(m)).join(' · ')}</div>
      <div class="hint">판정 대상인데 자료가 안 온 곳입니다. 미제출인지 판정 대상이 아닌지 확인하세요.</div>
    </section>` : ''}

    <div id="bulk-results"></div>
  `
  if(bulkResults) renderBulkResults()
}

document.addEventListener('input', (e)=>{
  if(e.target && e.target.classList.contains('bulk-tax')){
    bulkTaxInputs[e.target.dataset.company] = Math.max(0, Math.round(Number(e.target.value) || 0))
  }
})

document.addEventListener('click', async (e)=>{
  if(e.target && e.target.id === 'bulk-pick-all'){
    const boxes = document.querySelectorAll('.bulk-pick')
    const allOn = Array.from(boxes).every(b => b.checked)
    boxes.forEach(b => { b.checked = !allOn })
    return
  }
  if(e.target && e.target.id === 'bulk-run') await runBulkEvaluate()
})

function selectedBulkSheets(){
  const picked = []
  document.querySelectorAll('#bulk-content tr[data-sheet-index]').forEach(tr=>{
    const box = tr.querySelector('.bulk-pick')
    if(box && box.checked) picked.push(bulkParsed.sheets[Number(tr.dataset.sheetIndex)])
  })
  return picked
}

async function runBulkEvaluate(){
  const err = $('bulk-error')
  if(err) err.textContent = ''
  const picked = selectedBulkSheets()
  if(!picked.length){ if(err) err.textContent = '판정할 법인을 하나 이상 선택하세요.'; return }
  const body = {
    year: bulkParsed.year,
    companies: picked.map(s => ({
      company: s.company,
      total_sales: s.total_sales || 0,
      operating_income: s.operating_income || 0,
      corporate_tax: Number(bulkTaxInputs[s.company] || 0),
      related_sales: s.related_sales,
      article10_exclusions: s.article10_exclusions,
    })),
  }
  try{
    bulkResults = await post('/api/admin/bulk/evaluate', body)
    // 법인세를 얼마로 넣고 돌렸는지 결과에 남긴다. 나중에 표를 다시 볼 때 필요하다.
    bulkResults.corporate_tax = {...bulkTaxInputs}
    bulkResults.parsed = bulkParsed
    renderBulkResults()
    $('bulk-results')?.scrollIntoView({behavior: 'smooth', block: 'start'})
  }catch(e2){
    if(err) err.textContent = e2.message || '일괄 판정에 실패했습니다'
  }
}

function renderBulkResults(){
  const el = $('bulk-results')
  if(!el || !bulkResults) return
  const t = bulkResults.totals
  const rows = sortedResults(bulkResults.results).map(r=>{
    const by = criteriaByKey(r)
    const ratio = by.ratio || {}
    return `<tr>
      <td><strong>${escapeHtml(r.company)}</strong><div class="row-note">${escapeHtml(r.size || '')}</div></td>
      <td>${statusTag(r.taxable)}</td>
      <td style="min-width:210px">${meterHtml(r.taxation_ratio, r.normal_ratio)}</td>
      <td class="amount">${ratio.passed ? '+' : '−'}${pctStr(Math.abs(ratio.gap || 0))}</td>
      <td class="amount">${formatNum(r.total_sales)}원</td>
      <td class="amount">${formatNum(r.related_sales_total)}원</td>
      <td class="amount">${formatNum(r.deemed_gift_total)}원</td>
      <td class="amount">${formatNum(r.gift_tax_total)}원</td>
      <td class="amount"><strong>${formatNum(r.gift_tax_payable_total)}원</strong></td>
    </tr>`
  }).join('')

  el.innerHTML = `
    <section class="report-section" style="margin-top:30px">
      <div class="page-head" style="margin-bottom:16px">
        <div><h3 style="font-size:16px">일괄 판정 결과</h3>
          <div class="hint">${escapeHtml(bulkResults.year)}년 데이터 · ${escapeHtml(bulkResults.data_as_of || '')}</div></div>
        <div class="result-actions">
          <button type="button" id="bulk-csv" class="secondary">CSV 내려받기</button>
          <button type="button" class="secondary" data-goto="dashboard-page">대시보드로</button>
        </div>
      </div>

      <div class="tiles" style="margin-bottom:16px">
        ${tile('판정한 법인', t.evaluated + '곳')}
        ${tile('과세대상', t.taxable_count + '곳', t.taxable_count ? '납부세액이 발생합니다' : '없습니다',
               t.taxable_count ? 'bad' : 'ok')}
        ${tile('산출 증여세 합계', formatNum(t.gift_tax_total) + '원')}
        ${tile('납부 증여세 합계', formatNum(t.gift_tax_payable_total) + '원', '신고세액공제 3% 반영',
               t.gift_tax_payable_total ? 'bad' : '')}
      </div>

      ${(bulkResults.failed || []).length ? `<div class="report-notice"><strong>판정하지 못한 법인</strong><ul>${bulkResults.failed.map(f => `<li>${escapeHtml(f.company)} — ${escapeHtml(f.detail)}</li>`).join('')}</ul></div>` : ''}

      <div class="table-wrap">
        <table class="wide-table">
          <thead><tr>
            <th>법인</th><th>판정</th><th>판정비율 vs 정상거래비율</th><th class="amount">문턱 대비</th>
            <th class="amount">총매출</th><th class="amount">특수관계자 매출</th>
            <th class="amount">증여의제</th><th class="amount">산출세액</th><th class="amount">납부세액</th>
          </tr></thead>
          <tbody>${rows}</tbody>
          <tfoot><tr>
            <td colspan="4">합계</td>
            <td class="amount">${formatNum(t.total_sales)}원</td>
            <td class="amount">${formatNum(t.related_sales_total)}원</td>
            <td class="amount">${formatNum(t.deemed_gift_total)}원</td>
            <td class="amount">${formatNum(t.gift_tax_total)}원</td>
            <td class="amount">${formatNum(t.gift_tax_payable_total)}원</td>
          </tr></tfoot>
        </table>
      </div>
    </section>`
}

// 납부세액이 큰 곳 먼저, 세액이 같으면 문턱에 가까운 곳 먼저.
function sortedResults(results){
  return [...(results || [])].sort((a, b)=>{
    const d = Number(b.gift_tax_payable_total || 0) - Number(a.gift_tax_payable_total || 0)
    if(d !== 0) return d
    const ga = (criteriaByKey(a).ratio || {}).gap ?? -1
    const gb = (criteriaByKey(b).ratio || {}).gap ?? -1
    return gb - ga
  })
}

document.addEventListener('click', (e)=>{
  if(!e.target || e.target.id !== 'bulk-csv' || !bulkResults) return
  const rows = [['법인', '기업구분', '연도', '판정', '판정비율', '정상거래비율', '총매출',
                 '특수관계자매출', '제10항제외', '법인세상당액', '증여의제', '산출증여세', '납부증여세']]
  sortedResults(bulkResults.results).forEach(r=>{
    rows.push([r.company, r.size, r.year, r.taxable ? '과세대상' : '해당없음',
               pctStr(r.taxation_ratio), pctStr(r.normal_ratio, 0), r.total_sales,
               r.related_sales_total, r.article10_total,
               (bulkResults.corporate_tax || {})[r.company] || 0,
               r.deemed_gift_total, r.gift_tax_total, r.gift_tax_payable_total])
  })
  downloadCsv(`일괄판정_${bulkResults.year}.csv`, rows)
})


// ═══════════════════════════════════════════════════════════════════════════
// 5. 대시보드 (관리자)
// ═══════════════════════════════════════════════════════════════════════════
// 통합 판정 결과를 그대로 읽는다. 서버의 /api/admin/summary 는 입력값을 0 으로
// 넣고 돌려서 늘 '해당없음'이 나온다 — 실제 매출·영업이익이 들어와야 의미가 있다.

// 문턱까지 이만큼 이내면 '근접'으로 본다. 반기 데이터를 연환산한 값이라
// 연말에 뒤집힐 수 있는 구간이다.
const NEAR_THRESHOLD = 0.05

function renderDashboard(){
  const el = $('dashboard-content')
  if(!el) return
  if(!bulkResults){
    el.innerHTML = emptyBox('통합 판정을 먼저 실행하세요. 통합본을 올려 법인별로 판정하면 이 화면이 채워집니다.')
    return
  }
  const t = bulkResults.totals
  const results = bulkResults.results || []
  const parsed = bulkResults.parsed || {}

  const taxable = results.filter(r => r.taxable)
  // 지금은 해당없음이지만 문턱에 가까운 곳. 연말 재검토가 필요한 목록이다.
  const near = results
    .filter(r => !r.taxable)
    .map(r => ({r, gap: -(((criteriaByKey(r).ratio || {}).gap) ?? -1)}))
    .filter(x => x.gap >= 0 && x.gap <= NEAR_THRESHOLD)
    .sort((a, b) => a.gap - b.gap)

  const missing = parsed.missing_companies || []
  const evaluated = new Set(results.map(r => r.company))
  // 시트는 있는데 이번 합계에 안 들어간 법인. 상태로 거르면 '확인필요'인데 선택을
  // 해제한 법인이 어디에도 안 잡혀 조용히 사라진다 — 판정된 곳의 여집합으로 잡는다.
  const pending = (parsed.sheets || [])
    .filter(s => s.status !== '건너뜀' && !evaluated.has(s.company))
  // '확인필요'인데도 판정에 넣은 법인. 총매출이 임시값이면 비율이 터무니없어지고
  // 그 결과가 '해당없음'으로 조용히 표시된다 — 그대로 믿으면 안 된다.
  const shaky = (parsed.sheets || []).filter(s => s.status === '확인필요' && evaluated.has(s.company))
  const groupRatio = t.total_sales ? (t.related_sales_total / t.total_sales) : 0

  const nearRows = near.map(({r, gap})=>`
    <tr>
      <td><strong>${escapeHtml(r.company)}</strong><div class="row-note">${escapeHtml(r.size || '')}</div></td>
      <td style="min-width:210px">${meterHtml(r.taxation_ratio, r.normal_ratio)}</td>
      <td class="amount"><strong>${pctStr(gap)}</strong><div class="row-note">남은 여유</div></td>
      <td class="amount">${formatNum(((criteriaByKey(r).ratio || {}).headroom) || 0)}원<div class="row-note">이만큼 더 팔면 문턱</div></td>
    </tr>`).join('')

  const taxableRows = sortedResults(taxable).map(r=>`
    <tr>
      <td><strong>${escapeHtml(r.company)}</strong><div class="row-note">${escapeHtml(r.size || '')}</div></td>
      <td style="min-width:210px">${meterHtml(r.taxation_ratio, r.normal_ratio)}</td>
      <td class="amount">+${pctStr(((criteriaByKey(r).ratio || {}).gap) || 0)}</td>
      <td class="amount">${formatNum(r.deemed_gift_total)}원</td>
      <td class="amount"><strong>${formatNum(r.gift_tax_payable_total)}원</strong></td>
    </tr>`).join('')

  el.innerHTML = `
    <div class="tiles">
      ${tile('판정한 법인', t.evaluated + '곳', `${escapeHtml(bulkResults.year)}년 · ${escapeHtml(bulkResults.data_as_of || '')}`)}
      ${tile('과세대상', taxable.length + '곳', `전체의 ${t.evaluated ? Math.round(taxable.length / t.evaluated * 100) : 0}%`,
             taxable.length ? 'bad' : 'ok')}
      ${tile('납부 증여세 합계', formatNum(t.gift_tax_payable_total) + '원',
             `산출 ${formatNum(t.gift_tax_total)}원`, t.gift_tax_payable_total ? 'bad' : '')}
      ${tile('문턱 근접', near.length + '곳', `여유 ${pctStr(NEAR_THRESHOLD, 0)} 이내`, near.length ? 'bad' : '')}
      ${tile('그룹 특관매출 비율', pctStr(groupRatio), `총매출 ${formatNum(t.total_sales)}원`)}
    </div>

    ${shaky.length ? `<div class="report-notice" style="margin-top:20px;border-color:#F6D5D5;background:var(--bad-s)">
      <strong>이 법인의 판정은 그대로 믿으면 안 됩니다</strong>
      ${shaky.map(s => `<div>${escapeHtml(s.company)} — ${escapeHtml(s.warnings[0] || '확인 필요')}</div>`).join('')}
      <div style="margin-top:6px">총매출이 임시값이면 비율이 터무니없이 나오고, 그 결과가 '해당없음'으로 표시될 수 있습니다.</div>
    </div>` : ''}

    ${(pending.length || missing.length) ? `<div class="report-notice" style="margin-top:20px">
      <strong>이 숫자에 빠져 있는 법인</strong>
      ${pending.length ? `<div>시트는 있지만 판정 안 함 ${pending.length}곳 — ${pending.map(s => `${escapeHtml(s.company || s.excel_name)}<span class="muted">(${escapeHtml(s.status)})</span>`).join(', ')}</div>` : ''}
      ${missing.length ? `<div>통합본에 시트 없음 ${missing.length}곳 — ${missing.slice(0, 12).map(m => escapeHtml(m)).join(', ')}${missing.length > 12 ? ` 외 ${missing.length - 12}곳` : ''}</div>` : ''}
      <div style="margin-top:6px">위 합계는 <b>판정한 ${t.evaluated}곳만</b>의 값입니다.</div>
    </div>` : ''}

    <section class="report-section"><h3>과세대상 (${taxable.length}곳)</h3>
      ${taxable.length ? `<div class="table-wrap"><table class="wide-table">
        <thead><tr><th>법인</th><th>판정비율 vs 정상거래비율</th><th class="amount">초과분</th>
          <th class="amount">증여의제</th><th class="amount">납부세액</th></tr></thead>
        <tbody>${taxableRows}</tbody></table></div>`
        : emptyBox('과세대상으로 판정된 법인이 없습니다.')}
    </section>

    <section class="report-section"><h3>문턱 근접 — 연말 재검토 대상 (${near.length}곳)</h3>
      ${near.length ? `<div class="table-wrap"><table class="wide-table">
          <thead><tr><th>법인</th><th>판정비율 vs 정상거래비율</th><th class="amount">여유</th>
            <th class="amount">문턱까지 매출</th></tr></thead>
          <tbody>${nearRows}</tbody></table></div>
        <div class="hint">반기 실적을 연환산한 값이면 하반기 거래에 따라 뒤집힐 수 있습니다. 여유가 1%p 미만인 곳은 특히 그렇습니다.</div>`
        : emptyBox(`정상거래비율 문턱 ${pctStr(NEAR_THRESHOLD, 0)} 이내로 근접한 법인이 없습니다.`)}
    </section>

    <div class="report-note">
      <strong>이 화면의 출처</strong><br>
      통합 판정에서 계산한 결과를 그대로 보여줍니다. 서버에 저장되지 않으므로 새로고침하면 통합본을 다시 올려야 합니다.
      법인세 상당액은 통합 판정 화면에서 입력한 값이 쓰였습니다.
    </div>`
}
